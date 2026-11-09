"""MapGIS text grammar, independent of SHP, QGIS and any geographic region."""
from dataclasses import dataclass
import html
import re

from .errors import AnnotationError

CONTROL = re.compile(r'#([+\-=])')
FRACTION = re.compile(r'^/([^/]+)/([^/]+)/$')
SUPER = dict(zip('0123456789+-=()abcdefghijklmnoprstuvwxyz',
                 '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ'))
SUB = dict(zip('0123456789+-=()aehijklmnoprstuvx',
               '₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ'))


@dataclass(frozen=True)
class ParsedNote:
    raw: str
    unicode: str
    plain: str
    html: str
    kind: str
    warnings: tuple = ()


def parse_note(raw, *, strict=False):
    """Interpret #+, #-, #= and complete /numerator/denominator/ strings.

    Unknown controls remain in the text and are flagged; strict mode rejects
    them. HTML retains scripts where Unicode lacks a corresponding character.
    No stratigraphic symbols, rock names or ages are inferred or corrected.
    """
    if raw is None:
        raw = ''
    if not isinstance(raw, str):
        raise AnnotationError('Annotation must be a string or None')
    if not raw:
        return ParsedNote('', '', '', '', 'EMPTY')
    match = FRACTION.fullmatch(raw)
    if match:
        top = parse_note(match[1], strict=strict)
        bottom = parse_note(match[2], strict=strict)
        warnings = tuple(dict.fromkeys(('FRACTION_LINEAR',) + top.warnings + bottom.warnings))
        return ParsedNote(raw, top.unicode + ' / ' + bottom.unicode,
                          top.plain + ' / ' + bottom.plain,
                          '<sup>' + top.html + '</sup>⁄<sub>' + bottom.html + '</sub>',
                          'FRACTION', warnings)
    mode, start = '=', 0
    segments = []
    for match in CONTROL.finditer(raw):
        if match.start() > start:
            segments.append((mode, raw[start:match.start()]))
        mode, start = match[1], match.end()
    if start < len(raw):
        segments.append((mode, raw[start:]))
    unicode_parts, plain, markup, warnings = [], [], [], []
    for mode, value in segments:
        plain.append(value)
        escaped = html.escape(value).replace(' ', '&#160;')
        if '\t' in value or '\n' in value or '\r' in value:
            warnings.append('WHITESPACE_FORMATTING')
            escaped = escaped.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br/>').replace('\t', '&#160;' * 4)
        if mode == '=':
            unicode_parts.append(value)
            markup.append(escaped)
        else:
            table = SUPER if mode == '+' else SUB
            if any(char not in table for char in value):
                warnings.append('HTML_REQUIRED')
            unicode_parts.append(''.join(table.get(c, c) for c in value))
            tag = 'sup' if mode == '+' else 'sub'
            markup.append('<' + tag + '>' + escaped + '</' + tag + '>')
    if '#' in CONTROL.sub('', raw):
        if strict:
            raise AnnotationError('Unknown MapGIS control in ' + repr(raw))
        warnings.append('UNKNOWN_CONTROL')
    if CONTROL.sub('', raw) == '':
        warnings.append('EMPTY_CONTROL')
    return ParsedNote(raw, ''.join(unicode_parts), ''.join(plain), ''.join(markup),
                      'SCRIPT' if CONTROL.search(raw) else 'TEXT', tuple(dict.fromkeys(warnings)))
