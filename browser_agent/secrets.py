"""Secrets: the model names them, the harness types them, and the model never sees the values.

The model writes {{secret:NAME}} inside a text argument (browser_type, browser_fill_form, type_keys). The
harness swaps in the value just before the call reaches the browser. Every text that goes back to the model
(tool results, page snapshots, the generated Playwright code) is passed through redact(), which replaces any
value it finds with [secret:NAME]. Values are loaded on first use and kept only in memory.

Providers (config [secrets]):
  env           NAME -> environment variable named in [secrets.map] (or NAME itself)
  dotenv        a KEY=value file (dotenv_path); keep it chmod 600
  bitwarden-sm  Bitwarden Secrets Manager (`bws` CLI): NAME -> the secret's key in the project (or NAME itself).
                A machine-account access token is read from token_file (chmod 600); project_id limits the list.
                Unattended, scoped to one project, same secrets on every machine.
  bitwarden     Bitwarden password manager vault (`bw` CLI): with `folders` set, every item in those folders is
                usable as {{secret:item#field}} without configuration; or map NAME -> "item name::field"
                (field: username, password, uri, totp, notes, card number/expMonth/expYear/code/cardholderName,
                identity fields, or a custom field name). The vault must be unlocked: the session key is read
                from session_file (written by `bw unlock --raw`) or BW_SESSION - never the master password.
  1password     NAME -> "op://vault/item/field" in [secrets.map], read with the 1Password CLI `op read`;
                a service-account token is read from token_file (chmod 600) when set
"""
import json
import os
import re
import subprocess
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{secret:([A-Za-z0-9_.#-]+)\}\}")


class SecretError(Exception):
    pass


class Secrets:
    def __init__(self, cfg):
        self.provider = cfg.get("provider", "none")
        self.map = dict(cfg.get("map") or {})
        self.dotenv_path = cfg.get("dotenv_path") or ""
        self.token_file = cfg.get("token_file") or ""
        self.project_id = cfg.get("project_id") or ""
        self.session_file = cfg.get("session_file") or ""
        self.folders = list(cfg.get("folders") or [])  # bitwarden: only items in these vault folders
        self._values = {}
        self._dotenv = None

    # ---- what the model may know -----------------------------------------------------------------
    def names(self):
        if self.provider == "dotenv":
            return sorted(set(self._load_dotenv()) | set(self.map))
        if self.provider == "bitwarden-sm" and not self.map:
            return sorted(self._bws_list())
        if self.provider == "bitwarden" and self.folders:
            return sorted(set(self.map) | set(self._bw_discover()))
        return sorted(self.map)

    def _bw_discover(self):
        """Every usable field of every item in the allowed folders, named "item#field" - no mapping needed:
        put an item in the agents folder and the model can use {{secret:item#field}}."""
        env = self._bw_env()
        folders = [f for f in json.loads(self._run(["bw", "list", "folders"], env)) if f.get("name") in self.folders]
        names = []
        for f in folders:
            for it in json.loads(self._run(["bw", "list", "items", "--folderid", f["id"]], env)):
                n = it.get("name", "")
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", n):
                    continue  # names with spaces cannot appear in a placeholder; use the map for those
                for sec in ("login", "card", "identity"):
                    names += [f"{n}#{k}" for k, v in (it.get(sec) or {}).items() if isinstance(v, str) and v]
                names += [f"{n}#{x['name']}" for x in it.get("fields") or [] if x.get("name")]
                if it.get("login", {}) and it["login"].get("totp"):
                    names.append(f"{n}#totp")
        return names

    def _run(self, cmd, env_extra=None):
        env = dict(os.environ, **(env_extra or {}))
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        if r.returncode != 0:
            raise SecretError(f"{cmd[0]} failed: {r.stderr.strip()[:200]}")
        return r.stdout

    def _bw_env(self):
        session = os.environ.get("BW_SESSION")
        if not session and self.session_file and Path(self.session_file).expanduser().exists():
            session = Path(self.session_file).expanduser().read_text().strip()
        if not session:
            raise SecretError("Bitwarden vault is locked: run bw-agent-unlock (or export BW_SESSION=$(bw unlock --raw))")
        return {"BW_SESSION": session}

    def _bw_field(self, item, field):
        """One field of a vault item: login (username, password, uri), card (number, expMonth, expYear, code,
        cardholderName, brand), identity fields, notes, totp, or a custom field by its name."""
        env = self._bw_env()
        if not getattr(self, "_bw_synced", False):
            self._run(["bw", "sync"], env)
            self._bw_synced = True
        data = json.loads(self._run(["bw", "get", "item", item], env))
        if self.folders:
            if getattr(self, "_folder_ids", None) is None:
                self._folder_ids = {f["id"] for f in json.loads(self._run(["bw", "list", "folders"], env))
                                    if f.get("name") in self.folders}
            if data.get("folderId") not in self._folder_ids:
                raise SecretError(f"item {item!r} is not in an allowed folder ({', '.join(self.folders)})")
        if field == "totp":
            return self._run(["bw", "get", "totp", data["id"]], env).strip()
        if field == "notes":
            return data.get("notes")
        if field == "uri":
            uris = (data.get("login") or {}).get("uris") or []
            return uris[0].get("uri") if uris else None
        for section in ("login", "card", "identity"):
            if field in (data.get(section) or {}):
                return data[section][field]
        return next((f.get("value") for f in data.get("fields") or [] if f.get("name") == field), None)

    def _bws_list(self):
        """key -> value for every secret the machine account can read (cached; values stay in memory)."""
        if getattr(self, "_bws", None) is None:
            env = {"BWS_ACCESS_TOKEN": Path(self.token_file).expanduser().read_text().strip()} if self.token_file else {}
            cmd = ["bws", "secret", "list"] + ([self.project_id] if self.project_id else []) + ["--output", "json"]
            self._bws = {x["key"]: x["value"] for x in json.loads(self._run(cmd, env))}
        return self._bws

    # ---- loading ---------------------------------------------------------------------------------
    def _load_dotenv(self):
        if self._dotenv is None:
            self._dotenv = {}
            p = Path(self.dotenv_path).expanduser()
            if not p.exists():
                raise SecretError(f"dotenv file not found: {p}")
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                self._dotenv[k.strip()] = v.strip().strip('"').strip("'")
        return self._dotenv

    def get(self, name):
        if name in self._values:
            return self._values[name]
        if self.provider == "env":
            value = os.environ.get(self.map.get(name, name))
        elif self.provider == "dotenv":
            value = self._load_dotenv().get(self.map.get(name, name))
        elif self.provider == "bitwarden-sm":
            value = self._bws_list().get(self.map.get(name, name))
        elif self.provider == "bitwarden":
            ref = self.map.get(name) or (name.replace("#", "::", 1) if "#" in name else "")
            if not ref or "::" not in ref:
                raise SecretError(f'unknown secret {name}: use "item#field" or map it in [secrets.map]')
            item, field = ref.split("::", 1)
            value = self._bw_field(item, field)
        elif self.provider == "1password":
            ref = self.map.get(name)
            if not ref:
                raise SecretError(f"no op:// reference for {name} in [secrets.map]")
            env = dict(os.environ)
            if self.token_file:
                env["OP_SERVICE_ACCOUNT_TOKEN"] = Path(self.token_file).expanduser().read_text().strip()
            r = subprocess.run(["op", "read", "--no-newline", ref], capture_output=True, text=True, env=env,
                               timeout=60)
            if r.returncode != 0:
                raise SecretError(f"op read failed for {name}: {r.stderr.strip()[:200]}")
            value = r.stdout
        else:
            raise SecretError("no secret store configured ([secrets] provider)")
        if value is None or value == "":
            raise SecretError(f"secret {name} is empty or missing")
        self._values[name] = value
        return value

    # ---- substitution and redaction --------------------------------------------------------------
    def fill(self, obj):
        """Return a copy of a tool-argument structure with every {{secret:NAME}} replaced by its value."""
        if isinstance(obj, str):
            return PLACEHOLDER.sub(lambda m: self.get(m.group(1)), obj)
        if isinstance(obj, list):
            return [self.fill(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.fill(v) for k, v in obj.items()}
        return obj

    @staticmethod
    def uses(obj):
        return bool(PLACEHOLDER.search(str(obj)))

    def used(self):
        return bool(self._values)

    def scrub_dir(self, folder, max_bytes=50_000_000):
        """Redact secret values in every text file under folder (Playwright's page snapshots, trace and console
        files record typed values). Returns the number of files changed. Binary files (images, video) are skipped;
        they cannot be redacted."""
        changed = 0
        if not self._values:
            return 0
        for path in Path(folder).rglob("*"):
            if not path.is_file() or path.stat().st_size > max_bytes:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            red = self.redact(text)
            if red != text:
                path.write_text(red, encoding="utf-8")
                changed += 1
        return changed

    def redact(self, text):
        """Replace every loaded secret value in text by [secret:NAME] - also card numbers typed with spaces."""
        for name, value in self._values.items():
            if len(value) < 4:
                continue
            text = text.replace(value, f"[secret:{name}]")
            digits = re.sub(r"\D", "", value)
            if len(digits) >= 8 and len(digits) >= len(value.replace(" ", "").replace("-", "")):
                pattern = r"[\s-]?".join(map(re.escape, digits))
                text = re.sub(pattern, f"[secret:{name}]", text)
        return text
