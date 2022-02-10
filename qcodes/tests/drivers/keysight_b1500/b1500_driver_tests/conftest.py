import pytest
from pyvisa import VisaIOError

from qcodes.instrument_drivers.Keysight.keysightb1500.KeysightB1500_base import (
    KeysightB1500,
)


@pytest.fixture(name="b1500")
def _make_b1500(request):
    request.addfinalizer(KeysightB1500.close_all)

    try:
        resource_name = "insert_Keysight_B2200_VISA_resource_name_here"
        instance = KeysightB1500("SPA", address=resource_name)
    except (ValueError, VisaIOError):
        # Either there is no VISA lib installed or there was no real
        # instrument found at the specified address => use simulated instrument
        import qcodes.instrument.sims as sims

        path_to_yaml = sims.__file__.replace("__init__.py", "keysight_b1500.yaml")

        instance = KeysightB1500(
            "SPA", address="GPIB::1::INSTR", visalib=path_to_yaml + "@sim"
        )

    instance.get_status()
    instance.reset()

    yield instance
