"""Byte slices of already validated JSON. No number conversion or reserialization."""
from dataclasses import dataclass
import json


@dataclass(frozen=True, slots=True)
class SourceSlice:
    start: int
    end: int
    text: str


def _space(raw, pos):
    while pos < len(raw) and raw[pos] in b' \t\r\n':
        pos += 1
    return pos


def _end(raw, start):
    pos = start
    quoted = False
    depth = 0
    composite = raw[start] in b'[{'
    while pos < len(raw):
        byte = raw[pos]
        if quoted:
            if byte == 92:
                pos += 2
                continue
            if byte == 34:
                quoted = False
                if not composite:
                    return pos+1
        elif byte == 34:
            quoted = True
        elif composite:
            if byte in b'[{':
                depth += 1
            elif byte in b']}':
                depth -= 1
                if depth == 0:
                    return pos+1
        elif byte in b' \t\r\n,]}':
            return pos
        pos += 1
    return pos


def _members(raw, start, end):
    if raw[start] != 123:
        return
    pos = _space(raw,start+1)
    while pos < end and raw[pos] != 125:
        key_end = _end(raw,pos)
        key = json.loads(raw[pos:key_end])
        value_start = _space(raw,_space(raw,key_end)+1)
        value_end = _end(raw,value_start)
        yield key,value_start,value_end
        pos = _space(raw,value_end)
        if raw[pos] == 44:
            pos = _space(raw,pos+1)


def _elements(raw, start, end):
    if raw[start] != 91:
        return
    pos = _space(raw,start+1)
    while pos < end and raw[pos] != 93:
        stop = _end(raw,pos)
        yield SourceSlice(pos,stop,raw[pos:stop].decode('utf-8'))
        pos = _space(raw,stop)
        if raw[pos] == 44:
            pos = _space(raw,pos+1)


def source_slices(raw):
    start = _space(raw,0)
    for key,begin,end in _members(raw,start,_end(raw,start)):
        if key == 'items':
            items_source = SourceSlice(begin,end,raw[begin:end].decode('utf-8'))
            items = tuple(_elements(raw,begin,end))
            references = []
            for item in items:
                refs = ()
                for member,left,right in _members(raw,item.start,item.end):
                    if member == 'reference_links':
                        refs = tuple(_elements(raw,left,right))
                        break
                references.append(refs)
            return items_source,items,tuple(references)
    raise ValueError('Validated items source is absent')
