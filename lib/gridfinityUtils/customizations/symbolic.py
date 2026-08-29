"""Symbolic numbers that record how they were computed.

The generators compute every dimension in plain Python and hand Fusion the *result*
via ValueInput.createByReal(), so the derivation is lost. Sym is a float subclass:
existing code keeps working unchanged (native APIs accept it wherever a float is
expected), but arithmetic on it also builds the matching Fusion expression.

    baseWidth   = Sym('baseWidth', 4.2)
    xyClearance = Sym('xyClearance', 0.025)
    (baseWidth - xyClearance).expression   ->  'baseWidth - xyClearance'

Because the expressions come from executing the plugin's own arithmetic rather than
from a hand-written table, they follow upstream automatically when its formulas change.

UNITS
-----
Fusion's internal length unit is cm; emitted parameters are mm. Two rules follow:

* A bare number combined with a *length* must carry an explicit unit, or Fusion reads
  it in document units:  `binHeight * heightUnit - 1 mm`.
* A bare number combined with a *count* must stay unitless:  `binHeight - 1`.

So each Sym tracks whether it is a length, and dimensionality propagates through
arithmetic: length*scalar -> length, length/length -> scalar, and so on.
"""

MM_PER_CM = 10.0

# Expression precedence, used to add parentheses only where they are needed.
PREC_ATOM = 3
PREC_MUL = 2
PREC_ADD = 1


def isSym(value):
    return isinstance(value, Sym)


def isLengthOf(value, default=False):
    return value.isLength if isSym(value) else default


def formatNumber(value: float) -> str:
    text = '%.6f' % float(value)
    text = text.rstrip('0').rstrip('.')
    return text if text not in ('', '-') else '0'


def formatOperand(value, asLength: bool, minPrecedence: int = PREC_ATOM) -> str:
    """Render one side of a binary operation as Fusion expression text."""
    if isSym(value):
        text = value.expression
        return '(' + text + ')' if value.precedence < minPrecedence else text
    number = float(value)
    if asLength:
        return formatNumber(number * MM_PER_CM) + ' mm'
    return formatNumber(number)


class Sym(float):
    """A float that remembers its derivation as a Fusion expression."""

    __slots__ = ('expression', 'precedence', 'isLength')

    def __new__(cls, expression, value, precedence=PREC_ATOM, isLength=True):
        instance = float.__new__(cls, float(value))
        instance.expression = expression
        instance.precedence = precedence
        instance.isLength = isLength
        return instance

    def __repr__(self):
        return 'Sym(%r, %r, isLength=%r)' % (self.expression, float(self), self.isLength)

    def _binary(self, other, operator, reverse=False):
        left, right = (other, self) if reverse else (self, other)
        leftValue, rightValue = float(left), float(right)
        try:
            if operator == '+':
                value = leftValue + rightValue
            elif operator == '-':
                value = leftValue - rightValue
            elif operator == '*':
                value = leftValue * rightValue
            else:
                value = leftValue / rightValue
        except ZeroDivisionError:
            return NotImplemented

        leftIsLength = isLengthOf(left)
        rightIsLength = isLengthOf(right)

        if operator in ('+', '-'):
            precedence = PREC_ADD
            # Adding to a length keeps a length; a bare number takes the other side's
            # dimensionality so it is emitted with or without a unit accordingly.
            resultIsLength = leftIsLength or rightIsLength
            leftAsLength = rightAsLength = resultIsLength
        elif operator == '*':
            precedence = PREC_MUL
            resultIsLength = leftIsLength or rightIsLength
            # Scaling: the bare operand is a unitless multiplier.
            leftAsLength, rightAsLength = leftIsLength, rightIsLength
        else:
            precedence = PREC_MUL
            # length/length -> scalar; length/scalar -> length.
            resultIsLength = leftIsLength and not rightIsLength
            leftAsLength, rightAsLength = leftIsLength, rightIsLength

        rightMin = precedence + 1 if operator in ('-', '/') else precedence
        return Sym(
            '%s %s %s' % (
                formatOperand(left, leftAsLength, precedence),
                operator,
                formatOperand(right, rightAsLength, rightMin),
            ),
            value,
            precedence,
            resultIsLength,
        )

    def __add__(self, other):      return self._binary(other, '+')
    def __radd__(self, other):     return self._binary(other, '+', True)
    def __sub__(self, other):      return self._binary(other, '-')
    def __rsub__(self, other):     return self._binary(other, '-', True)
    def __mul__(self, other):      return self._binary(other, '*')
    def __rmul__(self, other):     return self._binary(other, '*', True)
    def __truediv__(self, other):  return self._binary(other, '/')
    def __rtruediv__(self, other): return self._binary(other, '/', True)

    def __neg__(self):
        return Sym('-' + formatOperand(self, self.isLength, PREC_MUL),
                   -float(self), PREC_MUL, self.isLength)

    def __pos__(self):
        return self

    def __abs__(self):
        return self if float(self) >= 0 else -self
