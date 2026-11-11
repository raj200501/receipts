# unitconv

Unit conversion for the shipping desk: parcel dimensions and weights, volumes, and the
temperatures of cold-chain shipments. The label printer service and the desk's scripts
use the library; people use the command line.

## Command line

    $ python3 -m unitconv convert 12 ft m
    12 ft = 3.6576 m
    $ python3 -m unitconv convert 5.5 pounds kg --precision 2
    5.5 lb = 2.49 kg
    $ python3 -m unitconv batch weights.txt --to kg
    12 lb = 5.4431 kg
    3.5 kg = 3.5 kg

`unitconv convert VALUE FROM TO` converts one value. Units can be given as symbols
(`ft`, `kg`, `C`) or as names (`feet`, `kilograms`, `celsius`); the output always uses
the symbols. Results are rounded to `--precision` decimal places (4 unless you say
otherwise) and printed without trailing zeros.

`unitconv batch FILE --to UNIT` converts every quantity in a text file, one per line,
such as `12 lb` or `3.5kg`. Blank lines and lines that start with `#` are skipped. If
any line cannot be converted, nothing is printed: the command names the line, for
example `unitconv: line 3: unknown unit 'pallets'`, and exits with status 2.

Every error (an unknown unit, units of different dimensions, a temperature below
absolute zero, a value that is not a number, a missing file) is printed to stderr as
`unitconv: ...`, and the command exits with status 2.

## Units

| Dimension | Base unit | Units |
| --- | --- | --- |
| length | m | mm, cm, m, km, in, ft, yd, mi, nmi |
| mass | kg | g, kg, t, oz, lb, st |
| volume | l | ml, l, m3, floz, pt, qt, gal |
| temperature | C | C, F, K |

`t` is the metric tonne, `st` the stone (14 lb), and `nmi` the nautical mile (1852 m).
The volumes `floz`, `pt`, `qt`, and `gal` are US customary units. The names that the
command line accepts for each unit are in `src/unitconv/aliases.py`.

## Library

    from unitconv import convert, dimension_of

    convert(12, "ft", "m")   # 3.6576
    dimension_of("gal")      # "volume"

`convert` takes unit symbols. It raises `UnknownUnitError` for a unit it does not know,
`DimensionMismatchError` for units of different dimensions, and `UnitError` for a
temperature below absolute zero; all of them are `UnitError`s, which are `ValueError`s.

## Development

    python3 -m pytest -v

The package lives in `src/unitconv/` and uses only the standard library.
