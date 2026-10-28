"""Just enough chess for puzzles: legal moves (no castling, no en passant), check, mate, SAN.

A board is a dict {"e4": "P", ...}: upper case is White, lower case is Black. Pawns promote to a queen.
"""
FILES = "abcdefgh"
KNIGHT = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]
DIAG = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
ORTHO = [(1, 0), (-1, 0), (0, 1), (0, -1)]


def sq(f, r):
    return FILES[f] + str(r + 1)


def fr(s):
    return FILES.index(s[0]), int(s[1]) - 1


def on(f, r):
    return 0 <= f < 8 and 0 <= r < 8


def side_of(p):
    return "w" if p.isupper() else "b"


def other(side):
    return "b" if side == "w" else "w"


def attacked(board, s, by):
    """Is square s attacked by any piece of colour `by`?"""
    f, r = fr(s)
    up = (lambda p: p.upper()) if by == "w" else (lambda p: p.lower())
    pr = r - 1 if by == "w" else r + 1           # rank a pawn of `by` must stand on to attack s
    for df in (-1, 1):
        if on(f + df, pr) and board.get(sq(f + df, pr)) == up("p"):
            return True
    for df, dr in KNIGHT:
        if on(f + df, r + dr) and board.get(sq(f + df, r + dr)) == up("n"):
            return True
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if (df or dr) and on(f + df, r + dr) and board.get(sq(f + df, r + dr)) == up("k"):
                return True
    for dirs, pieces in ((DIAG, ("b", "q")), (ORTHO, ("r", "q"))):
        for df, dr in dirs:
            x, y = f + df, r + dr
            while on(x, y):
                p = board.get(sq(x, y))
                if p:
                    if p in [up(c) for c in pieces]:
                        return True
                    break
                x, y = x + df, y + dr
    return False


def king(board, side):
    k = "K" if side == "w" else "k"
    return next(s for s, p in board.items() if p == k)


def in_check(board, side):
    return attacked(board, king(board, side), other(side))


def pseudo_moves(board, side):
    out = []
    for s, p in list(board.items()):
        if side_of(p) != side:
            continue
        f, r = fr(s)
        kind = p.lower()
        if kind == "p":
            d, start, last = (1, 1, 7) if side == "w" else (-1, 6, 0)
            if on(f, r + d) and not board.get(sq(f, r + d)):
                out.append((s, sq(f, r + d)))
                if r == start and not board.get(sq(f, r + 2 * d)):
                    out.append((s, sq(f, r + 2 * d)))
            for df in (-1, 1):
                if on(f + df, r + d):
                    t = board.get(sq(f + df, r + d))
                    if t and side_of(t) != side:
                        out.append((s, sq(f + df, r + d)))
        elif kind in ("n", "k"):
            steps = KNIGHT if kind == "n" else DIAG + ORTHO
            for df, dr in steps:
                if on(f + df, r + dr):
                    t = board.get(sq(f + df, r + dr))
                    if not t or side_of(t) != side:
                        out.append((s, sq(f + df, r + dr)))
        else:
            dirs = {"b": DIAG, "r": ORTHO, "q": DIAG + ORTHO}[kind]
            for df, dr in dirs:
                x, y = f + df, r + dr
                while on(x, y):
                    t = board.get(sq(x, y))
                    if t and side_of(t) == side:
                        break
                    out.append((s, sq(x, y)))
                    if t:
                        break
                    x, y = x + df, y + dr
    return out


def apply(board, move):
    a, b = move
    nb = dict(board)
    p = nb.pop(a)
    if p in "Pp" and b[1] in "18":
        p = "Q" if p == "P" else "q"
    nb[b] = p
    return nb


def legal_moves(board, side):
    return sorted(m for m in pseudo_moves(board, side) if not in_check(apply(board, m), side))


def is_mate(board, side):
    """Is `side` (to move) checkmated?"""
    return in_check(board, side) and not legal_moves(board, side)


def san(board, move):
    a, b = move
    p = board[a]
    side = side_of(p)
    capture = b in board
    if p in "Pp":
        s = (a[0] + "x" if capture else "") + b
        if b[1] in "18":
            s += "=Q"
    else:
        s = p.upper()
        twins = [m[0] for m in legal_moves(board, side) if m[1] == b and m[0] != a and board[m[0]] == p]
        if twins:
            if all(t[0] != a[0] for t in twins):
                s += a[0]
            elif all(t[1] != a[1] for t in twins):
                s += a[1]
            else:
                s += a
        s += ("x" if capture else "") + b
    nb = apply(board, move)
    if is_mate(nb, other(side)):
        s += "#"
    elif in_check(nb, other(side)):
        s += "+"
    return s


def mates_in_one(board, side):
    return [m for m in legal_moves(board, side) if is_mate(apply(board, m), other(side))]


def best_reply(board, side):
    """Black's reply in a mate-in-two: prefer a move after which White has no mate in one."""
    replies = legal_moves(board, side)
    for m in replies:
        if not mates_in_one(apply(board, m), other(side)):
            return m
    return replies[0] if replies else None


def mate_in_two_keys(board, side):
    keys = []
    for m in legal_moves(board, side):
        nb = apply(board, m)
        if is_mate(nb, other(side)):
            continue
        replies = legal_moves(nb, other(side))
        if replies and all(mates_in_one(apply(nb, r), side) for r in replies):
            keys.append(m)
    return keys


def parse(placement):
    """'Kg1 Ra1 Pf2 / kg8 pf7' style: White pieces before the slash, Black after (letter + square)."""
    white, black = placement.split("/")
    board = {}
    for tok in white.split():
        board[tok[1:]] = tok[0].upper()
    for tok in black.split():
        board[tok[1:]] = tok[0].lower()
    return board
