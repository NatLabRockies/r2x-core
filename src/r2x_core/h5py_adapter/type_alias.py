"""Type aliases for HDF5 reader data."""

import numpy as np

H5Label = str | bytes
H5Value = np.ndarray | list[str] | list[bytes]
H5Result = dict[str, H5Value]
