#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2016-2017 European Commission (JRC);
# Licensed under the EUPL (the 'Licence');
# You may not use this work except in compliance with the Licence.
# You may obtain a copy of the Licence at: http://ec.europa.eu/idabc/eupl

"""
It provides Ranges class.
"""
import itertools
import numpy as np
from .constants import NAME_REFERENCES
from .tokens.operand import _re_range, _range2parts, _index2col
import collections
from .errors import RangeValueError
import schedula.utils as sh_utl
import functools


def _has_same_sheet(x, y):
    return x and y and x['excel'] == y['excel'] and x['sheet'] == y['sheet']


def _have_intersect(x, y):
    if _has_same_sheet(x, y):
        z = {
            'excel': x['excel'], 'sheet': x['sheet'],
            'n1': max(y['n1'], x['n1']),
            'r1': max(int(y['r1']), int(x['r1'])),
            'n2': min(y['n2'], x['n2']),
            'r2': min(int(y['r2']), int(x['r2']))
        }

        if z['r1'] <= z['r2'] and z['n1'] <= z['n2']:
            return z
    return {}


def _single_intersect(x, y):
    z = _have_intersect(x, y)
    if z:
        z['r1'], z['r2'] = str(z['r1']), str(z['r2'])
        return dict(_range2parts().dsp(z, ['name', 'n1', 'n2']))
    return {}


def _split(base, rng, intersect=None):
    z = _have_intersect(base, rng)
    if not z:
        return rng,

    if intersect is not None:
        intersect.update(z)

    ranges = []
    rng = sh_utl.selector(('excel', 'sheet', 'n1', 'n2', 'r1', 'r2'), rng)
    rng['r1'], rng['r2'] = int(rng['r1']), int(rng['r2'])
    for i in ('n1', 'n2', 'r1', 'r2'):
        if z[i] != rng[i]:
            n = 1 - 2 * (int(i[1]) // 2)
            j = '%s%d' % (i[0], 2 - int(i[1]) // 2)
            r = sh_utl.combine_dicts(rng, {j: z[i] - n})
            r['r1'], r['r2'] = str(r['r1']), str(r['r2'])
            r = dict(_range2parts().dsp(r, ['name', 'n1', 'n2']))
            ranges.append(r)
            rng[i] = z[i]

    return tuple(ranges)


def _intersect(rng, ranges):
    it = map(functools.partial(_single_intersect, rng), ranges)
    return tuple(r for r in it if r)


def _merge_update(base, rng):
    if _has_same_sheet(base, rng):
        if base['n1'] == rng['n2'] and int(base['r2']) + 1 >= int(rng['r1']):
            base['r2'] = rng['r2']
            return True


def _get_indices_intersection(base, i):
    r, c = int(base['r1']), int(base['n1'])
    r = slice(int(i['r1']) - r, int(i['r2']) - r + 1)
    c = slice(int(i['n1']) - c, int(i['n2']) - c + 1)
    return r, c


class Ranges(object):
    format_range = _range2parts().dsp
    input_fields = ('excel', 'sheet', 'n1', 'n2', 'r1', 'r2')

    def __init__(self, ranges=(), values=None, is_set=False, all_values=True):
        self.ranges = ranges
        self.values = values or {}
        self.is_set = is_set
        self.all_values = all_values

    def pushes(self, refs, values=(), context=None):
        for r, v in itertools.zip_longest(refs, values, fillvalue=sh_utl.EMPTY):
            self.push(r, value=v, context=context)
        self.is_set = self.is_set or len(self.ranges) > 1
        return self

    def push(self, ref, value=sh_utl.EMPTY, context=None):
        context = context or {}
        m = _re_range.match(ref).groupdict().items()
        m = {k: v for k, v in m if v is not None}
        if 'ref' in m:
            raise ValueError
        i = sh_utl.combine_dicts(context, m)
        rng = self.format_range(i, ['name', 'n1', 'n2'])
        self.ranges += dict(rng),
        if value != sh_utl.EMPTY:
            self.values[rng['name']] = (rng, np.asarray(value))
        else:
            self.all_values = False
        return self

    def __and__(self, other):
        ranges = self.ranges[1:] + other.ranges
        rng = sh_utl.selector(self.input_fields, self.ranges[0])
        for k in ('r1', 'r2', 'n1', 'n2'):
            rng[k] = int(rng[k])

        for r in ranges:
            if not _has_same_sheet(rng, r):
                raise RangeValueError('{}:{}'.format(self, other))
            else:
                rng['r1'] = min(rng['r1'], int(r['r1']))
                rng['n1'] = min(rng['n1'], int(r['n1']))
                rng['r2'] = max(rng['r2'], int(r['r2']))
                rng['n2'] = max(rng['n2'], int(r['n2']))

        rng = dict(self.format_range(rng, ['name', 'n1', 'n2'])),
        return Ranges(rng, all_values=False)

    def __add__(self, ranges):
        base = self.ranges
        for r0 in ranges.ranges:
            stack = [r0]
            for b in base:
                s = stack.copy()
                stack = []
                for r in s:
                    stack.extend(_split(b, r))
            base += tuple(stack)
        values = sh_utl.combine_dicts(self.values, ranges.values)
        return Ranges(base, values, True, self.all_values and ranges.all_values)

    def __sub__(self, ranges):
        r = []
        for rng in ranges.ranges:
            r.extend(_intersect(rng, self.ranges))
        values = sh_utl.combine_dicts(self.values, ranges.values)
        is_set = self.is_set or ranges.is_set
        return Ranges(r, values, is_set, self.all_values and ranges.all_values)

    def simplify(self):
        rng = self.ranges
        if not rng:
            return self
        it = range(min(r['n1'] for r in rng), max(r['n2'] for r in rng) + 1)
        it = ['{0}:{0}'.format(_index2col(c)) for c in it]
        simpl = (self - Ranges(is_set=False).pushes(it))._merge()
        simpl.all_values = self.all_values
        return simpl

    def _merge(self):
        key = lambda x: (x['n1'], int(x['r1']), -x['n2'], -int(x['r2']))
        stack = []
        for r in sorted(self.ranges, key=key):
            if not (stack and _merge_update(stack[-1], r)):
                if stack:
                    i = sh_utl.selector(self.input_fields, stack.pop())
                    stack.append(dict(self.format_range(i, ['name'])))
                stack.append(r)
        return Ranges(tuple(stack), self.values, self.is_set, self.all_values)

    def __repr__(self):
        ranges = ', '.join(r['name'] for r in self.ranges)
        value = '={}'.format(self.value) if self.all_values else ''
        return '<%s>(%s)%s' % (self.__class__.__name__, ranges, value)

    @property
    def value(self):
        if not self.all_values:
            raise RangeValueError(str(self))
        stack, values = list(self.ranges), []
        while stack:
            for k, (rng, value) in sorted(self.values.items()):
                if not stack:
                    break
                i = {}
                new_rngs = _split(rng, stack[-1], intersect=i)
                if i:
                    stack.pop()
                    stack.extend(new_rngs)
                    r, c = _get_indices_intersection(rng, i)
                    values.append(value[:, c][r])

        if self.is_set:
            return np.concatenate([v.ravel() for v in values])
        return values[0]


class Values2Ranges(object):
    def __init__(self, ranges=None, outputs=None):
        self.ranges = ranges or Ranges()
        self.references = collections.OrderedDict()
        self.nodes = outputs or collections.OrderedDict()

    def push(self, node_id, rng):
        self.nodes[node_id] = rng
        self.ranges += rng

    def simplify(self):
        self.ranges = self.ranges.simplify()
        return self

    @property
    def inputs(self):
        rng = [r['name'] for r in self.ranges.ranges]
        if self.references:
            rng += list(self.references.values())[::-1] + [NAME_REFERENCES]
        return rng

    @property
    def outputs(self):
        return list(self.references) + list(self.nodes)

    def __call__(self, *args, **kwargs):
        res, args = [], list(args)
        if self.references:
            named_refs = args.pop()
            for k in self.references.values():
                if k in named_refs:
                    res.append(Ranges().push(named_refs[k], args.pop()))
                else:
                    args.pop()
                    res.append(sh_utl.NONE)
        val = {}
        for rng, v in zip(self.ranges.ranges, args):
            val[rng['name']] = rng, np.asarray(v)
        res += [Ranges(r.ranges, val, r.is_set) for r in self.nodes.values()]
        return sh_utl.bypass(*res)

    @property
    def __name__(self):
        return '=->(%s)' % ';'.join(self.inputs)