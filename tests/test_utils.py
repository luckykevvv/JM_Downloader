from jm_downloader.utils import safe_filename


def test_safe_filename_handles_windows_invalid_chars():
    assert safe_filename('A<B>C:D"E/F\\G|H?I*J. ') == "A_B_C_D_E_F_G_H_I_J"


def test_safe_filename_handles_reserved_name():
    assert safe_filename("CON") == "_CON"
