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
    $ python3 -m unitconv units
    length: mm cm m km in ft yd mi nmi
    mass: g kg t oz lb st
    volume: ml l m3 floz pt qt gal
    temperature: C F K

`unitconv convert VALUE FROM TO` converts one value. Units can be given as symbols
(`ft`, `kg`, `C`) or as names (`feet`, `kilograms`, `celsius`); the output always uses
the symbols. Results are rounded to `--precision` decimal places (4 unless you say
otherwise) and printed without trailing zeros.

`unitconv batch FILE --to UNIT` converts every quantity in a text file, one per line,
such as `12 lb` or `3.5kg`. Blank lines and lines that start with `#` are skipped. If
any line cannot be converted, nothing is printed: the command names the line, for
example `unitconv: line 3: unknown unit 'pallets'`, and exits with status 2.

`unitconv units` lists the units of the conversion table, one line per dimension.

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

Every unit works both as the unit of a value and as the unit to convert to.
`t` is the metric tonne, `st` the stone (14 lb), and `nmi` the nautical mile (1852 m).
The volumes `floz`, `pt`, `qt`, and `gal` are US customary units. The names that the
command line accepts for each unit are in `src/unitconv/aliases.py`.

## Library

    from unitconv import convert, dimension_of, register_unit

    convert(12, "ft", "m")   # 3.6576
    dimension_of("gal")      # "volume"

    register_unit("fur", "length", 201.168)   # the furlong
    convert(1, "mi", "fur")                   # 8.0

The units live in one conversion table, `UNITS` in `src/unitconv/conversions.py`. Each
entry has the unit's dimension, its factor, and an offset: a value `v` in the unit is
`v * factor + offset` in the base unit of the dimension (only the temperature scales
have an offset). To add a built-in unit, add an entry to the table (and its names to
`src/unitconv/aliases.py`). A program that needs a unit of its own can call
`register_unit(symbol, dimension, factor, offset=0.0)` at start-up; registering a symbol
that is already in the table raises `ValueError` and leaves the table unchanged.

`convert` takes unit symbols. It raises `UnknownUnitError` for a unit it does not know,
`DimensionMismatchError` for units of different dimensions, and `UnitError` for a
temperature below absolute zero; all of them are `UnitError`s, which are `ValueError`s.

## Development

    python3 -m pytest -v

The package lives in `src/unitconv/` and uses only the standard library.
