#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
德州扑克 · 服务器

只用 Python 3.7 及以上版本自带的标准库，不需要安装任何第三方包。

在自己电脑上运行（局域网玩）：
    python server.py            默认端口 8000
    python server.py 8080       换一个端口
然后让同一个 Wi-Fi 下的手机、平板或电脑用浏览器打开终端里显示的地址。

部署到云平台（不在一个网络也能玩）：见 README.md。平台给的端口从环境变量 PORT 读取；
设置环境变量 ROOM_CODE 后，加入牌桌需要先输入这个房间口令。

这台服务器是唯一掌握整副牌的一方：每台设备只会收到自己的底牌，
别人的底牌要到摊牌时才会发过去，所以在浏览器里查看网页源码也看不到。
电脑玩家也在这里运行，它们同样看不到别人的底牌。
"""
import copy
import itertools
import json
import os
import random
import secrets
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_PLAYERS = 6
TIME_BANK = 60                 # 开了行动计时后，每人整局额外有 60 秒可用
CLOCKS = (0, 20, 30, 45)       # 每次行动的时间，0 表示不限时
OFFLINE_GRACE = (30, 8)        # 轮到掉线的人时，等多少秒自动过牌或弃牌：(不限时, 限时)
SPEEDS = {'h10': ('hands', 10), 'm5': ('min', 5), 'm10': ('min', 10), 'm15': ('min', 15)}
MULT = [1, 2, 3, 4, 6, 8, 10, 15, 20, 30, 40, 60, 80, 100, 150, 200, 300, 400, 600, 800, 1000]
ANTE_FROM_LEVEL = 2            # 比赛第 3 级起收前注
HERE = os.path.dirname(os.path.abspath(__file__))
ROOM_CODE = os.environ.get('ROOM_CODE', '').strip()   # 房间口令，留空表示不需要
POLL_WAIT = 20            # 长轮询最多挂起多少秒
ONLINE_WINDOW = 30        # 多少秒没收到某台设备的请求，就算它掉线了
SIM_BUDGET = 0.35         # 电脑玩家每次思考最多用几秒 CPU（云平台免费机器 CPU 很少）
EQUITY_BUDGET = 0.6       # 全下胜率每次最多算几秒
RNG = random.SystemRandom()    # 洗牌用操作系统提供的随机数
MC = random.Random()           # 胜率模拟和电脑玩家只求快，用普通随机数即可
STREET = {'preflop': '翻牌前', 'flop': '翻牌', 'turn': '转牌', 'river': '河牌'}
RN = {10: '10', 11: 'J', 12: 'Q', 13: 'K', 14: 'A'}
GAME_FIELDS = ('stack', 'buyin', 'rebuys', 'bet', 'total', 'folded', 'allIn', 'acted', 'capped',
               'inHand', 'hole', 'last', 'aggr', 'pre', 'post', 'vol', 'handStart', 'place', 'bank', 'st')

# 电脑玩家的三档：value/raise 是相对胜率门槛（胜率 × 在局人数，1 表示平均水平）
BOTS = {
    'easy':   {'label': '新手', 'sims': 220, 'noise': 0.10, 'value': 1.55, 'raise': 1.90, 'aggr': 0.50,
               'margin': -0.06, 'bluff': 0.04, 'bluffRaise': 0.00, 'semi': 0.00, 'read': None, 'post': 0.0,
               'delay': (0.9, 1.8), 'showBluff': 0.0},
    'normal': {'label': '普通', 'sims': 420, 'noise': 0.06, 'value': 1.30, 'raise': 1.60, 'aggr': 0.75,
               'margin': 0.00, 'bluff': 0.08, 'bluffRaise': 0.03, 'semi': 0.20, 'read': (5, 8), 'post': 0.5,
               'delay': (1.0, 2.2), 'showBluff': 0.1},
    'hard':   {'label': '高手', 'sims': 700, 'noise': 0.03, 'value': 1.25, 'raise': 1.50, 'aggr': 0.85,
               'margin': 0.03, 'bluff': 0.05, 'bluffRaise': 0.02, 'semi': 0.22, 'read': (6, 9), 'post': 0.7,
               'model': True,
               'delay': (1.2, 2.8), 'showBluff': 0.3},
}
BOT_NAMES = ['老狐狸', '算盘', '铁头', '闪电', '石头', '阿尔法', '月光', '豆包', '团子']


def rn(r):
    return RN.get(r, str(r))


def fmt(n):
    return '{:,}'.format(n)


# 牌用一个整数表示：点数 * 4 + 花色，点数 2..14（A=14），花色 0..3 = 黑桃 红桃 方块 梅花
def c_rank(c):
    return c >> 2


def c_suit(c):
    return c & 3


# ---------------------------------------------------------------- 牌型判断

def score5(cs):
    """五张牌的牌力，返回列表，列表越大牌越大。"""
    r = sorted((c_rank(c) for c in cs), reverse=True)
    flush = all(c_suit(c) == c_suit(cs[0]) for c in cs)
    cnt = {}
    for x in r:
        cnt[x] = cnt.get(x, 0) + 1
    g = sorted(cnt.keys(), key=lambda x: (-cnt[x], -x))
    sh = 0
    if len(g) == 5:
        if r[0] - r[4] == 4:
            sh = r[0]
        elif r[0] == 14 and r[1] == 5:
            sh = 5
    if sh and flush:
        return [8, sh]
    if cnt[g[0]] == 4:
        return [7, g[0], g[1]]
    if cnt[g[0]] == 3 and cnt[g[1]] == 2:
        return [6, g[0], g[1]]
    if flush:
        return [5] + r
    if sh:
        return [4, sh]
    if cnt[g[0]] == 3:
        return [3] + g
    if cnt[g[0]] == 2 and cnt[g[1]] == 2:
        return [2] + g
    if cnt[g[0]] == 2:
        return [1] + g
    return [0] + r


def hand_name(s):
    k = s[0]
    a = s[1] if len(s) > 1 else 0
    b = s[2] if len(s) > 2 else 0
    if k == 8:
        return '皇家同花顺' if a == 14 else '同花顺 · {} 高'.format(rn(a))
    if k == 7:
        return '四条 {}'.format(rn(a))
    if k == 6:
        return '葫芦 · {} 带 {}'.format(rn(a), rn(b))
    if k == 5:
        return '同花 · {} 高'.format(rn(a))
    if k == 4:
        return '顺子 · {} 高'.format(rn(a))
    if k == 3:
        return '三条 {}'.format(rn(a))
    if k == 2:
        return '两对 · {} 和 {}'.format(rn(a), rn(b))
    if k == 1:
        return '一对 {}'.format(rn(a))
    return '高牌 {}'.format(rn(a))


def best(cards):
    """从 5~7 张牌里挑出最好的五张，返回 (牌力, 五张牌, 牌型名)。"""
    bs, bc = None, None
    for h in itertools.combinations(cards, 5):
        s = score5(h)
        if bs is None or s > bs:
            bs, bc = s, h
    return bs, list(bc), hand_name(bs)


def describe(hole, board):
    """亮出来的牌叫什么：有公共牌就说成牌，没有就说起手牌。"""
    if len(board) >= 3:
        return best(hole + board)[2]
    a, b = sorted((c_rank(c) for c in hole), reverse=True)
    if a == b:
        return '口袋对 ' + rn(a)
    return '{} {} {}'.format(rn(a), rn(b), '同花' if c_suit(hole[0]) == c_suit(hole[1]) else '杂色')


def chen(h):
    """Chen 公式：常用的起手牌强度估算，大约 -1 到 20 分。"""
    a, b = sorted((c_rank(c) for c in h), reverse=True)
    base = {14: 10, 13: 8, 12: 7, 11: 6}.get(a, a / 2.0)
    if a == b:
        return max(5, base * 2)
    s = base
    if c_suit(h[0]) == c_suit(h[1]):
        s += 2
    gap = a - b - 1
    s -= (0, 1, 2, 4, 5)[min(gap, 4)]
    if gap <= 1 and a < 12:
        s += 1
    return s


_CHEN_ALL = sorted((chen([a, b]) for a, b in itertools.combinations(range(8, 60), 2)), reverse=True)


def chen_top(frac):
    """起手牌里最强的 frac 比例，对应的 Chen 分数门槛。"""
    frac = min(1.0, max(0.02, frac))
    return _CHEN_ALL[min(len(_CHEN_ALL) - 1, int(frac * len(_CHEN_ALL)))]


PAIR_MIN = 16 ** 5   # eval7 结果大于等于它，说明至少有一对


# 七张牌的快速判断，只给胜率模拟和电脑玩家用；大小顺序和 score5 完全一致
def _st_high(mask):
    m = mask | 2 if mask & (1 << 14) else mask
    for h in range(14, 4, -1):
        if (m >> (h - 4)) & 31 == 31:
            return h
    return 0


def _top(mask, n, ex):
    out = []
    for r in range(14, 1, -1):
        if len(out) >= n:
            break
        if (mask >> r) & 1 and r not in ex:
            out.append(r)
    return out


def _pack(k, *xs):
    v = k
    xs = list(xs) + [0] * (5 - len(xs))
    for x in xs:
        v = v * 16 + x
    return v


def eval7(cs):
    rc = [0] * 15
    sc = [0, 0, 0, 0]
    sm = [0, 0, 0, 0]
    rm = 0
    for c in cs:
        r, s = c >> 2, c & 3
        rc[r] += 1
        sc[s] += 1
        sm[s] |= 1 << r
        rm |= 1 << r
    for s in range(4):
        if sc[s] >= 5:
            h = _st_high(sm[s])
            return _pack(8, h) if h else _pack(5, *_top(sm[s], 5, ()))
    q, tr, pr = 0, [], []
    for r in range(14, 1, -1):
        if rc[r] == 4:
            q = r
        elif rc[r] == 3:
            tr.append(r)
        elif rc[r] == 2:
            pr.append(r)
    if q:
        return _pack(7, q, _top(rm, 1, (q,))[0])
    if tr and (len(tr) > 1 or pr):
        return _pack(6, tr[0], max(tr[1] if len(tr) > 1 else 0, pr[0] if pr else 0))
    st = _st_high(rm)
    if st:
        return _pack(4, st)
    if tr:
        return _pack(3, tr[0], *_top(rm, 2, (tr[0],)))
    if len(pr) >= 2:
        return _pack(2, pr[0], pr[1], _top(rm, 1, (pr[0], pr[1]))[0])
    if pr:
        return _pack(1, pr[0], *_top(rm, 3, (pr[0],)))
    return _pack(0, *_top(rm, 5, ()))


# ---------------------------------------------------------------- 牌桌

class GameError(Exception):
    """玩家能看懂的错误，会原样显示在网页上。"""


def in_hand(p):
    return p is not None and p['inHand']


def live(p):
    return p is not None and p['inHand'] and not p['folded']


def move(p, a):
    a = max(0, min(a, p['stack']))
    p['stack'] -= a
    p['bet'] += a
    p['total'] += a
    if p['stack'] == 0:
        p['allIn'] = True


def cfg_error(c):
    for k in ('stack', 'sb', 'bb'):
        if not isinstance(c.get(k), int) or c[k] <= 0:
            return '筹码和盲注都要填大于 0 的整数'
    if c['bb'] < c['sb']:
        return '大盲不能小于小盲'
    if c['stack'] <= c['bb']:
        return '起始筹码必须大于大盲'
    if c['stack'] > 100000000:
        return '起始筹码最多 100,000,000'
    if c.get('mode') not in ('cash', 'tour'):
        return '模式不对'
    if c.get('speed') not in SPEEDS:
        return '升盲速度不对'
    if c.get('clock') not in CLOCKS:
        return '行动时间不对'
    return ''


class Table:
    def __init__(self):
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.version = 0
        self.online_set = frozenset()
        self.seats = [None] * MAX_PLAYERS
        self.cfg = {'mode': 'cash', 'stack': 1000, 'sb': 5, 'bb': 10, 'speed': 'm10', 'clock': 0, 'rit': False}
        self.g = None
        self.join_seq = 0
        self.eq_cache = (None, None)
        self.urls = []

    @staticmethod
    def now():
        return time.monotonic()

    # ---------- 小工具 ----------
    def changed(self):
        """状态变了：版本号加一，叫醒所有挂着的长轮询。调用时必须持有 self.lock。"""
        self.version += 1
        self.cond.notify_all()

    def is_online(self, p, now=None):
        if p['bot']:
            return True
        now = self.now() if now is None else now
        return p['polling'] > 0 or now - p['seen'] < ONLINE_WINDOW

    def touch(self, token, delta=0):
        s = self.seat_of(token)
        if s is not None:
            p = self.seats[s]
            p['seen'] = self.now()
            p['polling'] = max(0, p['polling'] + delta)

    def seat_of(self, token):
        if not token:
            return None
        for i, p in enumerate(self.seats):
            if p is not None and p['token'] == token:
                return i
        return None

    def host_seat(self):
        h = None
        for i, p in enumerate(self.seats):
            if p is not None and not p['bot'] and (h is None or p['seq'] < self.seats[h]['seq']):
                h = i
        return h

    def next_seat(self, s, pred):
        n = len(self.seats)
        for k in range(1, n + 1):
            t = (s + k) % n
            if pred(self.seats[t]):
                return t
        return -1

    def live_seats(self):
        return [i for i, p in enumerate(self.seats) if live(p)]

    def alive(self):
        """还能继续打下一手的人。现金局里电脑玩家输光会自动补码，所以也算。"""
        cash = self.g is not None and self.g['mode'] == 'cash'
        return [i for i, p in enumerate(self.seats)
                if p is not None and not p['leaving'] and p['place'] is None
                and (p['stack'] > 0 or (cash and p['bot']))]

    def pot_total(self):
        return sum(p['total'] for p in self.seats if in_hand(p))

    def blinds(self):
        g = self.g
        if g['mode'] == 'tour':
            m = MULT[g['level']]
            sb, bb = g['cfg']['sb'] * m, g['cfg']['bb'] * m
            ante = max(1, int(round(bb / 8.0))) if g['level'] >= ANTE_FROM_LEVEL else 0
            return sb, bb, ante
        return g['cfg']['sb'], g['cfg']['bb'], 0

    def log(self, **e):
        self.g['log'].append(e)

    def new_player(self, name, token, bot=None):
        self.join_seq += 1
        return {'token': token, 'name': name, 'seq': self.join_seq, 'bot': bot, 'polling': 0,
                'seen': self.now(), 'leaving': False, 'stack': 0, 'buyin': 0, 'rebuys': 0, 'bet': 0,
                'total': 0, 'folded': False, 'allIn': False, 'acted': False, 'capped': False, 'inHand': False,
                'hole': [], 'last': '', 'aggr': 0, 'pre': 0, 'post': 0, 'vol': False, 'handStart': 0, 'place': None, 'bank': 0,
                'st': [0, 0, 0]}

    # ---------- 开局与每一手 ----------
    def start_game(self):
        S = self.seats
        for i, p in enumerate(S):
            if p is not None and p['leaving']:
                S[i] = None
        ids = [i for i, p in enumerate(S) if p is not None]
        if len(ids) < 2:
            raise GameError('至少需要 2 名玩家才能开始，人不够可以加电脑玩家')
        if all(S[i]['bot'] for i in ids):
            raise GameError('至少要有一个真人玩家')
        c = dict(self.cfg)
        for i in ids:
            S[i].update(stack=c['stack'], buyin=c['stack'], rebuys=0, inHand=False, hole=[], place=None,
                        bank=TIME_BANK if c['clock'] else 0, st=[0, 0, 0])
        self.g = {'mode': c['mode'], 'cfg': c, 'hand': 0, 'level': 0, 'btn': -1, 'started': self.now(),
                  'deck': [], 'board': [], 'board2': None, 'runs': 1, 'k0': 0, 'street': 'preflop',
                  'toAct': 0, 'currentBet': 0, 'minRaise': c['bb'], 'pos': {'btn': -1, 'sb': -1, 'bb': -1},
                  'lastAct': None, 'result': None, 'runout': False, 'rit': None, 'runAt': None,
                  'gameOver': None, 'undo': None, 'log': [], 'prev': None, 'notice': '', 'pending': [],
                  'shown': [], 'places': [], 'turn': None, 'botAt': None, 'nextAt': None, 'resKey': None}
        self.start_hand()

    def start_hand(self):
        g, S = self.g, self.seats
        for i, p in enumerate(S):
            if p is not None and p['leaving']:
                S[i] = None
        if g['mode'] == 'cash':
            st = g['cfg']['stack']
            for p in S:
                if p is not None and p['bot'] and p['stack'] <= 0:
                    p['stack'] += st
                    p['buyin'] += st
                    p['rebuys'] += 1
                    g['pending'].append('{} 补码 {}'.format(p['name'], fmt(st)))
        if len(self.alive()) < 2:
            if g['result']:
                self.check_over()
            return False
        if g['hand'] > 0 and g['log']:
            g['prev'] = {'hand': g['hand'], 'log': g['log']}
        g['hand'] += 1
        for p in S:
            if p is not None:
                p.update(bet=0, total=0, folded=False, allIn=False, acted=False, capped=False, aggr=0, pre=0, post=0, vol=False,
                         inHand=p['stack'] > 0 and p['place'] is None, hole=[], last='', handStart=p['stack'])
                if p['inHand']:
                    p['st'] = [p['st'][0] + 1, p['st'][1], p['st'][2]]   # [发到牌的手数, 主动入池, 翻牌前加注]
        if g['btn'] < 0:
            g['btn'] = RNG.choice([i for i, p in enumerate(S) if in_hand(p)])
        else:
            g['btn'] = self.next_seat(g['btn'], in_hand)
        prev_lv = g['level']
        if g['mode'] == 'tour':
            kind, n = SPEEDS[g['cfg']['speed']]
            lv = (g['hand'] - 1) // n if kind == 'hands' else int((self.now() - g['started']) // (n * 60))
            g['level'] = min(lv, len(MULT) - 1)
        sb, bb, ante = self.blinds()
        g['notice'] = '盲注升至 {}/{}{}'.format(fmt(sb), fmt(bb), '，前注 {}'.format(fmt(ante)) if ante else '') \
            if g['level'] > prev_lv else ''
        deck = [r * 4 + s for r in range(2, 15) for s in range(4)]
        RNG.shuffle(deck)
        g.update(deck=deck, board=[], board2=None, runs=1, k0=0, street='preflop', result=None, runout=False,
                 rit=None, runAt=None, undo=None, lastAct=None, log=[], gameOver=None, shown=[], turn=None,
                 botAt=None, nextAt=None, resKey=None)
        for t in g['pending']:
            self.log(t='note', text=t)
        g['pending'] = []
        if g['notice']:
            self.log(t='note', text=g['notice'])
        n_in = sum(1 for p in S if in_hand(p))
        sbs = g['btn'] if n_in == 2 else self.next_seat(g['btn'], in_hand)
        bbs = self.next_seat(sbs, in_hand)
        g['pos'] = {'btn': g['btn'], 'sb': sbs, 'bb': bbs}
        if n_in > 2:
            self.log(t='note', text='庄家 ' + S[g['btn']]['name'])
        for _ in range(2):
            s = sbs
            for _ in range(n_in):
                S[s]['hole'].append(g['deck'].pop())
                s = self.next_seat(s, in_hand)
        if ante:
            for p in S:
                if in_hand(p):
                    a = min(ante, p['stack'])
                    p['stack'] -= a
                    p['total'] += a
                    if p['stack'] == 0:
                        p['allIn'] = True
            self.log(t='note', text='每人前注 {}'.format(fmt(ante)))
        move(S[sbs], sb)
        move(S[bbs], bb)
        for s, label in ((sbs, '小盲'), (bbs, '大盲')):
            self.log(t='act', n=S[s]['name'],
                     text='{} {}{}'.format(label, fmt(S[s]['bet']), '（全下）' if S[s]['allIn'] else ''))
        g['currentBet'] = max(p['bet'] for p in S if p is not None)
        g['minRaise'] = bb
        g['toAct'] = self.next_seat(bbs, in_hand)
        self.proceed()
        return True

    # ---------- 下注轮 ----------
    def needs(self, i):
        g, p = self.g, self.seats[i]
        if not live(p) or p['allIn']:
            return False
        others = any(j != i and live(o) and not o['allIn'] for j, o in enumerate(self.seats))
        if not others and p['bet'] >= g['currentBet']:
            return False
        return (not p['acted']) or p['bet'] < g['currentBet']

    def find_need(self, start):
        n = len(self.seats)
        for k in range(n):
            s = (start + k) % n
            if self.needs(s):
                return s
        return -1

    def proceed(self):
        g, S = self.g, self.seats
        L = self.live_seats()
        if len(L) == 1:
            self.fold_win(L[0])
            return
        s = self.find_need(g['toAct'])
        if s >= 0:
            g['toAct'] = s
            return
        self.return_uncalled(False)
        if sum(1 for i in L if not S[i]['allIn']) <= 1:
            self.start_runout()
            return
        if g['street'] == 'river':
            self.showdown(False)
            return
        self.next_street()
        g['toAct'] = self.find_need((g['btn'] + 1) % len(S))

    def return_uncalled(self, quiet):
        ps = [p for p in self.seats if in_hand(p)]
        if len(ps) < 2:
            return
        ps.sort(key=lambda p: -p['bet'])
        hi, d = ps[0], ps[0]['bet'] - ps[1]['bet']
        if d <= 0:
            return
        hi['stack'] += d
        hi['bet'] -= d
        hi['total'] -= d
        if hi['stack'] > 0:
            hi['allIn'] = False
        if not quiet:
            self.log(t='note', text='退回 {} 没被跟上的 {}'.format(hi['name'], fmt(d)))

    def deal_to(self, cards):
        g = self.g
        g['deck'].pop()  # 烧一张
        add = [g['deck'].pop() for _ in range(3 if not cards else 1)]
        cards += add
        return add

    def next_street(self):
        g = self.g
        for p in self.seats:
            if p is not None:
                p.update(bet=0, acted=False, capped=False, last='')
        g['currentBet'] = 0
        g['minRaise'] = self.blinds()[1]
        g['lastAct'] = None
        add = self.deal_to(g['board'])
        g['street'] = {3: 'flop', 4: 'turn', 5: 'river'}[len(g['board'])]
        self.log(t='board', st=g['street'], cards=add)

    # ---------- 全下：亮牌、跑两次投票、自动发牌 ----------
    def start_runout(self):
        g, S = self.g, self.seats
        for p in S:
            if p is not None:
                p['bet'] = 0
        L = self.live_seats()
        g['shown'] = sorted(set(g['shown']) | set(L))   # 全下且没人能再下注，所有人亮牌
        if len(g['board']) >= 5:
            self.showdown(True)
            return
        g['k0'] = len(g['board'])
        if g['cfg']['rit']:
            votes = {str(i): (self.bot_rit_vote(i) if S[i]['bot'] else None) for i in L}
            g['rit'] = {'votes': votes, 'at': self.now() + 12}
            self.log(t='note', text='全下了，等大家选择跑一次还是跑两次')
            if all(v is not None for v in votes.values()):
                self.resolve_rit()
        else:
            self.log(t='note', text='没人能再下注，亮牌后自动发完公共牌')
            g['runout'] = True
            g['runAt'] = self.now() + 1.4

    def resolve_rit(self):
        g = self.g
        twice = all(v is True for v in g['rit']['votes'].values())
        g['runs'] = 2 if twice else 1
        self.log(t='note', text='所有人同意，跑两次，每个底池分两半' if twice else '跑一次')
        g['rit'] = None
        g['runout'] = True
        g['runAt'] = self.now() + 1.0

    def runout_step(self):
        g = self.g
        if len(g['board']) < 5:
            add = self.deal_to(g['board'])
            g['street'] = {3: 'flop', 4: 'turn', 5: 'river'}[len(g['board'])]
            self.log(t='board', st=g['street'], cards=add)
            g['runAt'] = self.now() + 1.6
        elif g['runs'] == 2 and (g['board2'] is None or len(g['board2']) < 5):
            if g['board2'] is None:
                g['board2'] = g['board'][:g['k0']]
            add = self.deal_to(g['board2'])
            self.log(t='board', st={3: 'flop', 4: 'turn', 5: 'river'}[len(g['board2'])], cards=add, run=2)
            g['runAt'] = self.now() + 1.6
        else:
            self.showdown(True)

    # ---------- 结算 ----------
    def showdown(self, tabled):
        g, S = self.g, self.seats
        L = self.live_seats()
        ins = [i for i, p in enumerate(S) if in_hand(p)]
        boards = [g['board']]
        if g['runs'] == 2 and g['board2'] and len(g['board2']) == 5:
            boards.append(g['board2'])
        evs = [{i: best(S[i]['hole'] + b) for i in L} for b in boards]
        levels = sorted(set(S[i]['total'] for i in ins if S[i]['total'] > 0))
        pots, prev, carry = [], 0, 0
        for lv in levels:   # 按投入额分层，每层就是一个底池（主池、边池）
            amt = sum(min(S[i]['total'], lv) - min(S[i]['total'], prev) for i in ins)
            elig = [i for i in L if S[i]['total'] >= lv]
            if amt > 0:
                if not elig:
                    if pots:
                        pots[-1]['amt'] += amt
                    else:
                        carry += amt
                elif pots and pots[-1]['elig'] == elig:
                    pots[-1]['amt'] += amt
                else:
                    pots.append({'amt': amt + carry, 'elig': elig})
                    carry = 0
            prev = lv
        n = len(S)
        order = [(g['btn'] + k) % n for k in range(1, n + 1)]   # 庄家左手起，零头先给这边
        won = [0] * n
        must_show = set()
        for pt in pots:
            parts = [pt['amt']] if len(boards) == 1 else [pt['amt'] - pt['amt'] // 2, pt['amt'] // 2]
            pt['ws'] = []
            for bi, amt in enumerate(parts):
                ev = evs[bi]
                top = max(ev[i][0] for i in pt['elig'])
                w = [i for i in order if i in pt['elig'] and ev[i][0] == top]
                share, rem = divmod(amt, len(w))
                for i in w:
                    won[i] += share + (1 if rem > 0 else 0)
                    if rem > 0:
                        rem -= 1
                pt['ws'].append(w)
                if len(pt['elig']) > 1:
                    must_show.update(w)
        for i, p in enumerate(S):
            if p is not None:
                p['stack'] += won[i]
                p['bet'] = 0
        shown = set(g['shown']) | must_show | (set(L) if tabled else set())
        g['shown'] = sorted(shown)
        for i in L:
            if i in shown:
                hn = ' / '.join(ev[i][2] for ev in evs) if len(evs) > 1 else evs[0][i][2]
                self.log(t='show', n=S[i]['name'], cards=list(S[i]['hole']), hn=hn)
            else:
                self.log(t='note', text='{} 盖牌'.format(S[i]['name']))
        for k, pt in enumerate(pots):
            label = ('主池' if k == 0 else '边池' + (' {}'.format(k) if len(pots) > 2 else '')) if len(pots) > 1 else '底池'
            for bi, w in enumerate(pt['ws']):
                run = '第{}次 · '.format('一二'[bi]) if len(boards) > 1 else ''
                amt = pt['amt'] if len(boards) == 1 else (pt['amt'] - pt['amt'] // 2 if bi == 0 else pt['amt'] // 2)
                who = '、'.join(S[i]['name'] for i in w)
                how = ' · ' + evs[bi][w[0]][2] if len(pt['elig']) > 1 else ''
                verb = '平分' if len(w) > 1 else '赢得'
                self.log(t='result', text='{}{} {}{} {}{}'.format(run, who, verb, label, fmt(amt), how))
        hi = []
        for bi, ev in enumerate(evs):
            cards = set()
            for i in L:
                if won[i] > 0 and i in shown and any(i in pt['ws'][bi] for pt in pots):
                    cards.update(ev[i][1])
            hi.append(sorted(cards))
        g['result'] = {'type': 'show', 'runs': len(boards), 'won': won, 'pot': sum(pt['amt'] for pt in pots),
                       'pots': [{'amt': pt['amt'], 'elig': pt['elig'], 'ws': pt['ws']} for pt in pots],
                       'hi': hi, 'names': {str(i): S[i]['name'] for i in ins}}
        g['runout'] = False
        g['runAt'] = None
        self.finish_hand()

    def fold_win(self, w):
        g, S = self.g, self.seats
        self.return_uncalled(True)
        pot = self.pot_total()
        won = [0] * len(S)
        won[w] = pot
        S[w]['stack'] += pot
        for p in S:
            if p is not None:
                p['bet'] = 0
        self.log(t='result', text='{} 赢得 {}'.format(S[w]['name'], fmt(pot)))
        g['result'] = {'type': 'fold', 'won': won, 'pot': pot, 'w': w, 'runs': 1, 'hi': [],
                       'names': {str(i): p['name'] for i, p in enumerate(S) if in_hand(p)}}
        p = S[w]
        if p['bot'] and BOTS[p['bot']]['showBluff'] and MC.random() < BOTS[p['bot']]['showBluff']:
            weak = chen(p['hole']) < 5 if len(g['board']) < 3 else best(p['hole'] + g['board'])[0][0] == 0
            if weak:
                self.show(w)
        self.finish_hand()

    def finish_hand(self):
        g, S = self.g, self.seats
        if g['mode'] == 'tour':
            busted = [i for i, p in enumerate(S) if p is not None and p['inHand'] and p['stack'] <= 0 and p['place'] is None]
            busted.sort(key=lambda i: S[i]['handStart'])   # 同一手出局的，开局时筹码少的名次靠后
            self.assign_places(busted)
            self.assign_places([i for i, p in enumerate(S) if p is not None and p['leaving'] and p['place'] is None])
        self.check_over()

    def assign_places(self, ids):
        """按从差到好的顺序传入。名次 = 还没定名次的人数（含自己）。"""
        g, S = self.g, self.seats
        for i in ids:
            S[i]['place'] = sum(1 for p in S if p is not None and p['place'] is None)
            g['places'].append({'name': S[i]['name'], 'place': S[i]['place'], 'hand': g['hand'], 'bot': S[i]['bot']})

    def check_over(self):
        g = self.g
        if not g['result']:
            return
        a = self.alive()
        g['gameOver'] = a[0] if len(a) == 1 else (None if a else -1)
        if g['mode'] == 'tour' and len(a) == 1 and self.seats[a[0]]['place'] is None:
            self.seats[a[0]]['place'] = 1
            g['places'].append({'name': self.seats[a[0]]['name'], 'place': 1, 'hand': g['hand'],
                                'bot': self.seats[a[0]]['bot']})

    def show(self, seat):
        g, p = self.g, self.seats[seat]
        if seat in g['shown'] or not p['inHand'] or not p['hole']:
            return
        g['shown'] = sorted(set(g['shown']) | {seat})
        self.log(t='show', n=p['name'], cards=list(p['hole']), hn=describe(p['hole'], g['board']) + '（主动亮牌）')

    # ---------- 玩家操作 ----------
    def raise_info(self, seat):
        g, S = self.g, self.seats
        p = S[seat]
        to_call = max(0, g['currentBet'] - p['bet'])
        others = [o for j, o in enumerate(S) if j != seat and live(o)]
        my_max = p['bet'] + p['stack']
        opp_max = max([o['bet'] + o['stack'] for o in others] or [0])
        max_to = min(my_max, opp_max)
        can = (not p['capped']) and any(not o['allIn'] for o in others) and p['stack'] > to_call and max_to > g['currentBet']
        min_to = min(g['currentBet'] + g['minRaise'], max_to)
        return {'can': can, 'toCall': to_call, 'minTo': min_to, 'maxTo': max_to, 'myMax': my_max,
                'pot': self.pot_total(), 'step': self.blinds()[0], 'isBet': g['currentBet'] == 0,
                'currentBet': g['currentBet']}

    def snapshot(self):
        g = {k: copy.deepcopy(v) for k, v in self.g.items() if k not in ('undo', 'prev')}
        ps = {i: {f: copy.deepcopy(p[f]) for f in GAME_FIELDS} for i, p in enumerate(self.seats) if p is not None}
        return {'g': g, 'p': ps}

    def can_undo(self, seat):
        g = self.g
        if not g or g['mode'] != 'cash':
            return False
        u = g['undo']
        if not u or u['seat'] != seat or g['runout'] or g['rit'] or u['b'] != len(g['board']):
            return False
        if g['result']:
            return g['result']['type'] == 'fold'
        return g['toAct'] != seat

    def act(self, seat, typ, amount=None, auto=None):
        g, S = self.g, self.seats
        if not g or g['result'] or g['runout'] or g['rit']:
            raise GameError('现在不能下注')
        if g['toAct'] != seat:
            raise GameError('还没轮到你')
        p = S[seat]
        to_call = max(0, g['currentBet'] - p['bet'])
        ri = None
        if typ == 'raise':
            ri = self.raise_info(seat)
            if not ri['can']:
                raise GameError('现在不能加注')
        elif typ == 'check':
            if to_call > 0:
                raise GameError('需要跟注，不能过牌')
        elif typ == 'fold':
            if to_call == 0:
                raise GameError('可以直接过牌，不用弃牌')
        elif typ != 'call':
            raise GameError('不认识这个操作')
        t = g['turn']
        if t and t.get('bank') and t.get('bankStart') is not None:
            p['bank'] = max(0, int(p['bank'] - (self.now() - t['bankStart'])))
        g['undo'] = None if (auto or p['bot']) else {'seat': seat, 'b': len(g['board']), 'snap': self.snapshot()}
        g['notice'] = ''
        if typ == 'fold':
            p['folded'] = True
            p['last'] = '弃牌'
        elif typ == 'check':
            p['last'] = '过牌'
        elif typ == 'call':
            a = min(to_call, p['stack'])
            move(p, a)
            p['last'] = '全下 {}'.format(fmt(p['bet'])) if p['allIn'] else '跟注 {}'.format(fmt(a))
        else:
            try:
                to = int(amount)
            except (TypeError, ValueError):
                to = ri['minTo']
            to = max(ri['minTo'], min(ri['maxTo'], to))
            was_bet = g['currentBet'] == 0
            move(p, to - p['bet'])
            inc = to - g['currentBet']
            full = was_bet or inc >= g['minRaise']   # 全下不足一次完整加注时，不重新开放加注
            if inc >= g['minRaise']:
                g['minRaise'] = inc
            g['currentBet'] = to
            p['aggr'] += 1
            if g['street'] == 'preflop':
                p['pre'] += 1
            else:
                p['post'] += 1
            for j, o in enumerate(S):
                if j == seat or not live(o) or o['allIn']:
                    continue
                if full:
                    o['acted'] = False
                    o['capped'] = False
                elif o['acted']:
                    o['acted'] = False
                    o['capped'] = True
            if p['allIn']:
                p['last'] = '全下 {}'.format(fmt(to))
            else:
                p['last'] = ('下注 {}' if was_bet else '加注到 {}').format(fmt(to))
        p['acted'] = True
        if g['street'] == 'preflop' and typ in ('call', 'raise'):
            if not p['vol']:
                p['st'] = [p['st'][0], p['st'][1] + 1, p['st'][2]]
            if typ == 'raise' and p['pre'] == 1:
                p['st'] = [p['st'][0], p['st'][1], p['st'][2] + 1]
            p['vol'] = True   # 翻牌前主动入池，电脑玩家用它来估计对手的牌力范围
        g['lastAct'] = {'seat': seat, 'text': p['last']}
        self.log(t='act', n=p['name'], text=('{}，自动'.format(auto) if auto else '') + p['last'])
        g['toAct'] = (seat + 1) % len(S)
        self.proceed()

    def undo(self, seat):
        if not self.can_undo(seat):
            raise GameError('现在不能撤销')
        snap, prev = self.g['undo']['snap'], self.g['prev']
        g = copy.deepcopy(snap['g'])
        g['undo'] = None
        g['prev'] = prev
        g['turn'] = None
        g['resKey'] = None
        self.g = g
        for i, f in snap['p'].items():
            if self.seats[i] is not None:
                self.seats[i].update(copy.deepcopy(f))

    def rebuy(self, seat):
        g, p = self.g, self.seats[seat]
        if not g:
            raise GameError('牌局还没开始')
        if g['mode'] != 'cash':
            raise GameError('比赛里不能补码')
        if p['stack'] > 0:
            raise GameError('你还有筹码，不需要补码')
        st = g['cfg']['stack']
        p['stack'] += st
        p['buyin'] += st
        p['rebuys'] += 1
        g['pending'].append('{} 补码 {}'.format(p['name'], fmt(st)))
        g['undo'] = None
        if g['result']:
            self.check_over()

    def remove(self, seat, why):
        """离开或被移出。手里还有牌的人当作弃牌，下一手开始前让出座位。"""
        S, g = self.seats, self.g
        p = S[seat]
        if g is None:
            S[seat] = None
            return
        g['undo'] = None
        g['pending'].append('{} {}'.format(p['name'], why))
        if g['result'] or not p['inHand']:
            if g['mode'] == 'tour' and p['place'] is None and p['stack'] > 0:
                p['leaving'] = True
                self.assign_places([seat])
            S[seat] = None
            if g['result']:
                self.check_over()
        else:
            p['leaving'] = True
            if live(p) and not p['allIn'] and not g['runout'] and not g['rit']:
                p['folded'] = True
                p['last'] = '离开'
                self.log(t='act', n=p['name'], text='离开牌桌，视为弃牌')
                if g['toAct'] == seat:
                    g['toAct'] = (seat + 1) % len(S)
                self.proceed()
        if all(x is None or x['bot'] for x in S):
            self.g = None
            for i in range(len(S)):
                if S[i] is not None:
                    S[i].update(inHand=False, hole=[], bet=0, total=0, place=None)

    # ---------- 定时：倒计时、电脑玩家、自动发牌、自动下一手 ----------
    def after_change(self):
        """每次状态变化后整理定时器。"""
        g, S = self.g, self.seats
        if not g:
            return
        now = self.now()
        active = not g['result'] and not g['runout'] and not g['rit']
        if active:
            key = [g['hand'], len(g['log']), g['toAct']]
            if g['turn'] is None or g['turn']['key'] != key:
                p = S[g['toAct']]
                T = g['cfg']['clock']
                g['turn'] = {'key': key, 'start': now, 'deadline': now + T if T else None, 'total': T,
                             'bank': False, 'bankStart': None}
                g['botAt'] = now + MC.uniform(*BOTS[p['bot']]['delay']) if p['bot'] else None
        else:
            g['turn'] = None
            g['botAt'] = None
        if g['result']:
            if g['resKey'] != g['hand']:
                g['resKey'] = g['hand']
                humans = any(p is not None and not p['bot'] and p['stack'] > 0 and p['place'] is None
                             and not p['leaving'] for p in S)
                if g['gameOver'] is not None:
                    g['nextAt'] = None
                elif not humans:
                    g['nextAt'] = now + 3
                elif g['cfg']['clock']:
                    g['nextAt'] = now + 7
                else:
                    g['nextAt'] = None
            elif g['gameOver'] is not None:
                g['nextAt'] = None

    def tick(self):
        with self.lock:
            g, S = self.g, self.seats
            if not g:
                return
            now = self.now()
            did = False
            online = frozenset(i for i, p in enumerate(S) if p is not None and self.is_online(p, now))
            if online != self.online_set:
                self.online_set = online
                did = True
            try:
                if g['rit']:
                    if now >= g['rit']['at'] or all(v is not None for v in g['rit']['votes'].values()):
                        self.resolve_rit()
                        did = True
                elif g['runout']:
                    if g['runAt'] is not None and now >= g['runAt']:
                        self.runout_step()
                        did = True
                elif g['result']:
                    if g['nextAt'] is not None and now >= g['nextAt']:
                        if not self.start_hand():
                            g['nextAt'] = None
                        did = True
                elif g['turn']:
                    s, t = g['toAct'], g['turn']
                    p = S[s]
                    if p['bot']:
                        if g['botAt'] is not None and now >= g['botAt']:
                            typ, amt = self.bot_decide(s)
                            self.act(s, typ, amt)
                            did = True
                    else:
                        grace = OFFLINE_GRACE[1 if t['total'] else 0]
                        if not self.is_online(p, now) and now >= max(t['start'], p['seen'] + ONLINE_WINDOW) + grace:
                            self.auto_act(s, '掉线')
                            did = True
                        elif t['deadline'] is not None and now >= t['deadline']:
                            if not t['bank'] and p['bank'] > 0:
                                t['bank'] = True
                                t['bankStart'] = now
                                t['deadline'] = now + p['bank']
                                t['total'] = p['bank']
                            else:
                                if t['bank']:
                                    p['bank'] = 0
                                    t['bank'] = False
                                self.auto_act(s, '超时')
                            did = True
            except Exception:
                traceback.print_exc()
            if did:
                self.after_change()
                self.changed()

    def auto_act(self, seat, why):
        p = self.seats[seat]
        typ = 'check' if self.g['currentBet'] <= p['bet'] else 'fold'
        self.act(seat, typ, auto=why)

    # ---------- 电脑玩家 ----------
    def sim_equity(self, hole, opp, ranges, sims, board=None):
        board = self.g['board'] if board is None else board
        known = set(hole) | set(board)
        deck = [c for c in range(8, 60) if c not in known]
        need = 5 - len(board)
        k = len(opp)
        if k == 0:
            return 1.0
        wins = 0.0
        n = 0
        stop = time.monotonic() + SIM_BUDGET
        while n < sims and (n < 40 or time.monotonic() < stop):
            n += 1
            for _try in range(10):
                pick = MC.sample(deck, 2 * k + need)
                hs = [pick[2 * j:2 * j + 2] for j in range(k)]
                ok = True
                for j in range(k):
                    rg = ranges.get(opp[j])
                    if not rg:
                        continue
                    thr, q = rg
                    if thr is not None and chen(hs[j]) < thr:
                        ok = False
                        break
                    if q and len(board) >= 3 and eval7(hs[j] + board) < PAIR_MIN and MC.random() < q:
                        ok = False   # 翻牌后主动下注的人，多半至少有一对
                        break
                if ok:
                    break
            b = board + pick[2 * k:]
            mine = eval7(hole + b)
            top = max(eval7(h + b) for h in hs)
            if mine > top:
                wins += 1
            elif mine == top:
                wins += 0.5
        return wins / n

    def bot_decide(self, seat):
        g, S = self.g, self.seats
        p = S[seat]
        B = BOTS[p['bot']]
        ri = self.raise_info(seat)
        opp = [i for i in self.live_seats() if i != seat]
        k = len(opp)
        ranges = {}   # 对手 -> (起手牌 Chen 分数门槛, 翻牌后下注时没成对的牌被排除的概率)
        for i in opp:
            o = S[i]
            thr = None
            if B.get('model'):
                # 高手：按这个对手实际的入池率和加注率推算翻牌前范围（先验 25% / 12%）
                dealt, vpip, pfr = o['st']
                v = (vpip + 2.5) / (dealt + 10.0)
                r = (pfr + 1.2) / (dealt + 10.0)
                if o['pre'] >= 2:
                    thr = chen_top(r / 3.0)
                elif o['pre'] == 1:
                    thr = chen_top(r)
                elif o['vol']:
                    thr = chen_top(v)
            elif B['read']:
                if o['pre'] >= 2:
                    thr = B['read'][1]
                elif o['pre'] == 1:
                    thr = B['read'][0]
            q = B['post'] if o['post'] >= 1 else 0.0
            if thr is not None or q:
                ranges[i] = (thr, q)
        eq = self.sim_equity(p['hole'], opp, ranges, B['sims'] if k <= 3 else B['sims'] // 2)
        eq = min(1.0, max(0.0, eq + MC.uniform(-B['noise'], B['noise'])))
        rel = eq * (k + 1)
        pot, call, stack = ri['pot'], ri['toCall'], p['stack']
        pre = g['street'] == 'preflop'
        _, bb, _ = self.blinds()
        heads = k == 1
        can = ri['can']

        def size(frac):
            if pre:
                if ri['currentBet'] <= bb:
                    limpers = sum(1 for j, o in enumerate(S) if j != seat and live(o) and o['bet'] >= bb) - 1
                    to = bb * 3 + max(0, limpers) * bb
                else:
                    to = ri['currentBet'] * 3
            elif ri['isBet']:
                to = frac * pot
            else:
                to = ri['currentBet'] + frac * (pot + call)
            to = int(round(to / float(ri['step']))) * ri['step']
            return max(ri['minTo'], min(ri['maxTo'], to))

        if call == 0:
            if can and rel >= B['value']:
                if p['bot'] == 'hard' and rel > 2.3 and g['street'] == 'flop' and MC.random() < 0.25:
                    return 'check', None   # 偶尔慢打
                if stack <= pot * 1.2 and rel >= 1.3:
                    return 'raise', ri['maxTo']
                return 'raise', size(0.5 + min(0.45, (rel - B['value']) * 0.5))
            if can and not pre and B['semi'] and g['street'] != 'river' and 0.30 < eq < 0.55 and MC.random() < B['semi']:
                return 'raise', size(0.6)      # 半诈唬
            if can and not pre and MC.random() < B['bluff'] * (1.6 if heads else 0.6):
                return 'raise', size(0.55)     # 诈唬
            return 'check', None
        odds = call / float(pot + call)
        if can and rel >= B['raise'] and MC.random() < B['aggr']:
            if stack <= (pot + call) * 1.5 or (rel > 2.6 and MC.random() < 0.25):
                return 'raise', ri['maxTo']
            return 'raise', size(0.8)
        need = odds + B['margin']
        if p['bot'] == 'easy' and call <= pot * 0.35:
            need -= 0.08
        if eq >= need:
            return 'call', None
        if can and heads and not pre and g['street'] != 'river' and MC.random() < B['bluffRaise']:
            return 'raise', size(1.0)
        return 'fold', None

    def bot_rit_vote(self, i):
        e = self.equity()
        return e['p'][i] < 0.75 and MC.random() < 0.7

    # ---------- 胜率（全下后亮牌时显示） ----------
    def equity(self):
        g, S = self.g, self.seats
        board = g['board2'] if g['board2'] is not None else g['board']
        key = (id(g), g['hand'], tuple(g['board']), tuple(g['board2'] or ()))
        if self.eq_cache[0] == key:
            return self.eq_cache[1]
        L = self.live_seats()
        known = set(board) | set(g['board'])
        for p in S:
            if in_hand(p):
                known.update(p['hole'])
        rest = [c for c in range(8, 60) if c not in known]
        need = 5 - len(board)
        base = [S[i]['hole'] + board for i in L]
        sh = [0.0] * len(S)
        n = 0

        def run(add):
            scores = [eval7(b + add) for b in base]
            mx = max(scores)
            w = [L[k] for k, s in enumerate(scores) if s == mx]
            for i in w:
                sh[i] += 1.0 / len(w)

        if need <= 0:
            run([])
            n = 1
        elif need == 1:
            for x in rest:
                run([x])
                n += 1
        else:
            exact = need == 2
            combos = list(itertools.combinations(rest, 2)) if exact else None
            if exact:
                MC.shuffle(combos)
            limit = len(combos) if exact else 4000
            stop = time.monotonic() + EQUITY_BUDGET
            while n < limit and (n < 200 or time.monotonic() < stop):
                run(list(combos[n]) if exact else MC.sample(rest, need))
                n += 1
            need = need if n >= limit and exact else 3   # 没算完全部组合就标成估算
        v = {'p': [x / n for x in sh], 'exact': need <= 2}
        self.eq_cache = (key, v)
        return v

    # ---------- 发给每台设备的画面数据 ----------
    def view(self, token):
        g, S = self.g, self.seats
        me = self.seat_of(token)
        now = self.now()
        shown = set(g['shown']) if g else set()
        seats = []
        for i, p in enumerate(S):
            if p is None:
                seats.append(None)
                continue
            d = {'name': p['name'], 'online': self.is_online(p, now), 'stack': p['stack'],
                 'leaving': p['leaving'], 'bot': p['bot']}
            if g:
                vis = i == me or i in shown
                d.update(inHand=p['inHand'], folded=p['folded'], allIn=p['allIn'], bet=p['bet'], last=p['last'],
                         buyin=p['buyin'], rebuys=p['rebuys'], place=p['place'],
                         capped=p['capped'] if i == me else False, nHole=len(p['hole']), shown=i in shown,
                         hole=p['hole'] if vis else None, bank=p['bank'] if i == me else None)
                if i in shown and p['hole']:
                    d['hn'] = describe(p['hole'], g['board'])
                    if g['board2'] and len(g['board2']) >= 3:
                        d['hn2'] = describe(p['hole'], g['board2'])
            seats.append(d)
        out = {'me': me, 'host': self.host_seat(), 'max': MAX_PLAYERS, 'cfg': self.cfg, 'seats': seats,
               'urls': self.urls, 'game': None, 'bots': {k: v['label'] for k, v in BOTS.items()}}
        if g:
            sb, bb, ante = self.blinds()
            active = not g['result'] and not g['runout'] and not g['rit']
            gv = {'mode': g['mode'], 'hand': g['hand'], 'level': g['level'] + 1, 'sb': sb, 'bb': bb, 'ante': ante,
                  'stack': g['cfg']['stack'], 'clockOn': g['cfg']['clock'], 'ritOn': g['cfg']['rit'],
                  'board': g['board'], 'board2': g['board2'], 'runs': g['runs'], 'street': g['street'],
                  'toAct': g['toAct'] if active else None, 'currentBet': g['currentBet'], 'pot': self.pot_total(),
                  'pos': g['pos'], 'lastAct': g['lastAct'], 'result': g['result'], 'runout': g['runout'],
                  'gameOver': g['gameOver'] if g['result'] else None, 'notice': g['notice'], 'log': g['log'],
                  'prev': g['prev'], 'places': g['places'], 'canUndo': me is not None and self.can_undo(me)}
            if g['runout'] or g['rit']:
                gv['equity'] = self.equity()
            if g['rit']:
                gv['rit'] = {'votes': g['rit']['votes'], 'left': max(0.0, g['rit']['at'] - now)}
            t = g['turn']
            if active and t and t['deadline'] is not None:
                gv['clock'] = {'seat': g['toAct'], 'left': max(0.0, t['deadline'] - now), 'total': t['total'],
                               'bank': t['bank']}
            if g['result'] and g['nextAt'] is not None:
                gv['nextLeft'] = max(0.0, g['nextAt'] - now)
            if g['mode'] == 'tour':
                kind, n = SPEEDS[g['cfg']['speed']]
                if g['level'] < len(MULT) - 1:
                    m = MULT[g['level'] + 1]
                    gv['nextBlinds'] = [g['cfg']['sb'] * m, g['cfg']['bb'] * m]
                    if kind == 'hands':
                        gv['handsLeft'] = n - ((g['hand'] - 1) % n)
                    else:
                        gv['levelLeft'] = max(0.0, (g['level'] + 1) * n * 60 - (now - g['started']))
            if me is not None and active and g['toAct'] == me:
                gv['ri'] = self.raise_info(me)
            if me is not None and S[me]['inHand'] and S[me]['hole']:
                gv['myHand'] = describe(S[me]['hole'], g['board'])
                gv['canShow'] = bool(g['result']) and me not in shown
            out['game'] = gv
        return out

    # ---------- 长轮询：浏览器带着自己看到的版本号来问，有新变化就立刻返回，否则最多等 POLL_WAIT 秒 ----------
    def poll(self, token, since, code):
        with self.cond:
            if ROOM_CODE and self.seat_of(token) is None and code != ROOM_CODE:
                return {'v': self.version, 's': {'locked': True, 'me': None, 'max': MAX_PLAYERS}}
            was_online = self.seat_of(token) is not None and self.is_online(self.seats[self.seat_of(token)])
            self.touch(token, +1)
            if self.seat_of(token) is not None and not was_online:
                self.changed()
            try:
                stop = time.monotonic() + POLL_WAIT
                while self.version <= since:
                    left = stop - time.monotonic()
                    if left <= 0:
                        break
                    self.cond.wait(left)
                return {'v': self.version, 's': self.view(token)}
            finally:
                self.touch(token, -1)

    # ---------- 网页发来的请求 ----------
    def handle(self, body):
        op = body.get('op')
        token = str(body.get('token') or '')
        with self.lock:
            if op == 'join':
                if ROOM_CODE and self.seat_of(token) is None and str(body.get('code') or '').strip() != ROOM_CODE:
                    raise GameError('房间口令不对')
                res = self.op_join(token, body.get('name'))
            else:
                seat = self.seat_of(token)
                if seat is None:
                    raise GameError('你已经不在牌桌上了，请重新加入')
                fn = getattr(self, 'op_' + str(op), None) if op in OPS else None
                if fn is None:
                    raise GameError('不认识这个操作')
                res = fn(seat, body) or {}
            self.after_change()
            self.changed()
        res['ok'] = True
        return res

    def require_host(self, seat):
        if seat != self.host_seat():
            raise GameError('只有房主可以这样做')

    def free_seat(self):
        free = [i for i, p in enumerate(self.seats) if p is None]
        if not free:
            raise GameError('牌桌已满，最多 {} 人'.format(MAX_PLAYERS))
        return free[0]

    def seat_newcomer(self, p, what):
        """牌局中途坐下的人从下一手开始玩。"""
        g = self.g
        if g:
            if g['mode'] == 'tour':
                raise GameError('比赛已经开始，现在只能旁观')
            st = g['cfg']['stack']
            p.update(stack=st, buyin=st, bank=TIME_BANK if g['cfg']['clock'] else 0)
            g['pending'].append('{} {}'.format(p['name'], what))
            g['undo'] = None
        i = self.free_seat()
        self.seats[i] = p
        if g and g['result']:
            self.check_over()
        return i

    def op_join(self, token, name):
        name = ' '.join(str(name or '').split())[:12]
        if not name:
            raise GameError('先填一个名字')
        s = self.seat_of(token)
        if s is not None:
            self.seats[s]['name'] = name
            return {'token': token, 'seat': s}
        tok = secrets.token_urlsafe(16)
        i = self.seat_newcomer(self.new_player(name, tok), '加入牌桌')
        return {'token': tok, 'seat': i}

    def op_addbot(self, seat, body):
        self.require_host(seat)
        level = body.get('level')
        if level not in BOTS:
            raise GameError('没有这个难度')
        used = {p['name'] for p in self.seats if p is not None}
        names = [n for n in BOT_NAMES if '电脑·' + n not in used] or ['{}号'.format(len(used) + 1)]
        p = self.new_player('电脑·' + MC.choice(names), None, bot=level)
        self.seat_newcomer(p, '（{}电脑）入座'.format(BOTS[level]['label']))

    def op_rmbot(self, seat, body):
        self.require_host(seat)
        try:
            t = int(body.get('seat'))
        except (TypeError, ValueError):
            raise GameError('没有这个座位')
        if not 0 <= t < len(self.seats) or self.seats[t] is None or not self.seats[t]['bot']:
            raise GameError('这个座位不是电脑玩家')
        self.remove(t, '被移出')

    def op_config(self, seat, body):
        self.require_host(seat)
        if self.g:
            raise GameError('牌局进行中不能改设置，先回到大厅')
        c = dict(self.cfg)
        for k in ('stack', 'sb', 'bb', 'clock'):
            if k in body:
                try:
                    c[k] = int(body[k])
                except (TypeError, ValueError):
                    raise GameError('请输入整数')
        for k in ('mode', 'speed'):
            if k in body:
                c[k] = str(body[k])
        if 'rit' in body:
            c['rit'] = bool(body['rit'])
        err = cfg_error(c)
        if err:
            raise GameError(err)
        self.cfg = c

    def op_start(self, seat, body):
        self.require_host(seat)
        if self.g:
            raise GameError('牌局已经开始了')
        self.start_game()

    def op_newgame(self, seat, body):
        self.require_host(seat)
        if not self.g:
            raise GameError('牌局还没开始')
        self.start_game()

    def op_lobby(self, seat, body):
        self.require_host(seat)
        self.g = None
        for i, p in enumerate(self.seats):
            if p is not None:
                if p['leaving']:
                    self.seats[i] = None
                else:
                    p.update(inHand=False, hole=[], bet=0, total=0, folded=False, allIn=False, last='', place=None)

    def op_act(self, seat, body):
        self.act(seat, body.get('type'), body.get('amount'))

    def op_undo(self, seat, body):
        self.undo(seat)

    def op_next(self, seat, body):
        g = self.g
        if not g or not g['result'] or body.get('hand') != g['hand']:
            return {}
        if not self.start_hand():
            raise GameError('至少要有两个人有筹码才能开下一手')

    def op_rebuy(self, seat, body):
        self.rebuy(seat)

    def op_show(self, seat, body):
        g = self.g
        if not g or not g['result']:
            raise GameError('这手结束后才能亮牌')
        self.show(seat)

    def op_rit(self, seat, body):
        g = self.g
        if not g or not g['rit'] or str(seat) not in g['rit']['votes']:
            raise GameError('现在不用选择')
        if g['rit']['votes'][str(seat)] is None:
            g['rit']['votes'][str(seat)] = bool(body.get('twice'))
        if all(v is not None for v in g['rit']['votes'].values()):
            self.resolve_rit()

    def op_leave(self, seat, body):
        self.remove(seat, '离开了牌桌')

    def op_kick(self, seat, body):
        self.require_host(seat)
        try:
            t = int(body.get('seat'))
        except (TypeError, ValueError):
            raise GameError('没有这个座位')
        if t == seat or not 0 <= t < len(self.seats) or self.seats[t] is None:
            raise GameError('没有这个玩家')
        if self.is_online(self.seats[t]) or self.seats[t]['bot']:
            raise GameError('只能移出已经离线的玩家')
        self.remove(t, '被房主移出')


OPS = {'config', 'start', 'newgame', 'lobby', 'act', 'undo', 'next', 'rebuy', 'leave', 'kick',
       'addbot', 'rmbot', 'show', 'rit'}
TABLE = Table()


def ticker():
    while True:
        time.sleep(0.2)
        TABLE.tick()


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = 'HoldemLAN/2.0'

    def log_message(self, fmt_, *args):
        pass

    def send_body(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ('/', '/index.html'):
            try:
                with open(os.path.join(HERE, 'index.html'), 'rb') as f:
                    self.send_body(200, f.read(), 'text/html; charset=utf-8')
            except OSError:
                self.send_body(500, '找不到 index.html'.encode('utf-8'), 'text/plain; charset=utf-8')
        elif u.path == '/poll':
            q = parse_qs(u.query)
            try:
                since = int(q.get('v', ['-1'])[0])
            except ValueError:
                since = -1
            try:
                res = TABLE.poll(q.get('token', [''])[0], since, q.get('code', [''])[0].strip())
                body = json.dumps(res, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            except Exception:
                traceback.print_exc()
                self.send_body(500, b'error', 'text/plain')
                return
            self.send_body(200, body, 'application/json; charset=utf-8')
        elif u.path == '/healthz':
            self.send_body(200, b'ok', 'text/plain')
        else:
            self.send_body(404, b'not found', 'text/plain')

    def do_POST(self):
        if urlparse(self.path).path != '/api':
            self.send_body(404, b'not found', 'text/plain')
            return
        try:
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(min(n, 20000)).decode('utf-8') or '{}') if n else {}
            if not isinstance(body, dict):
                raise ValueError
            res = TABLE.handle(body)
        except GameError as e:
            res = {'ok': False, 'error': str(e)}
        except (ValueError, UnicodeDecodeError):
            res = {'ok': False, 'error': '请求格式不对'}
        except Exception:
            traceback.print_exc()
            res = {'ok': False, 'error': '服务器出错了，看一下电脑上的终端'}
        self.send_body(200, json.dumps(res, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')


def lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))   # 不会真的发包，只是让系统选出局域网网卡的地址
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith('127.')]


def main():
    port = int(os.environ.get('PORT') or 8000)
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print('端口要是数字，比如：python server.py 8080')
            sys.exit(1)
    if not os.path.exists(os.path.join(HERE, 'index.html')):
        print('找不到 index.html，请把它和 server.py 放在同一个文件夹里。')
        sys.exit(1)
    try:
        httpd = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    except OSError:
        print('端口 {} 已被占用，换一个试试：python server.py {}'.format(port, port + 1))
        sys.exit(1)
    httpd.daemon_threads = True
    rail = (os.environ.get('RAILWAY_PUBLIC_DOMAIN') or '').strip()
    public = (os.environ.get('PUBLIC_URL') or os.environ.get('RENDER_EXTERNAL_URL') or ('https://' + rail if rail else '')).strip().rstrip('/')
    TABLE.urls = [public] if public else ['http://{}:{}'.format(ip, port) for ip in lan_ips()]
    threading.Thread(target=ticker, daemon=True).start()
    print()
    print('  德州扑克服务器已启动，端口 {}'.format(port), flush=True)
    if public:
        print('  公网地址：' + public, flush=True)
    else:
        print('  让同一个 Wi-Fi 下的手机、平板、电脑用浏览器打开：')
        for u in TABLE.urls or ['（没找到局域网地址，请检查这台电脑是否连上了 Wi-Fi）']:
            print('      ' + u)
        print('  这台电脑自己也可以打开 http://localhost:{}'.format(port))
    print('  房间口令：' + ('已设置' if ROOM_CODE else '未设置，任何拿到地址的人都能加入'), flush=True)
    print('  按 Ctrl+C 关闭服务器', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n  服务器已关闭')


if __name__ == '__main__':
    main()
