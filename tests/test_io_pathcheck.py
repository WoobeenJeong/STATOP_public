import time

from statop.io.pathcheck import check_path


def test_green_yellow_red(tmp_path):
    assert check_path(tmp_path, "write").color == "green"
    assert check_path(tmp_path / "new_sub" / "a.json", "write").color == "yellow"
    assert check_path(tmp_path / "no.json", "read").color == "red"
    assert check_path("/root/forbidden/x.json", "write").color == "red"

    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)  # 읽기 전용 폴더
    assert check_path(ro, "write").color == "red"
    assert check_path(ro, "read").color == "green"
    ro.chmod(0o700)


def test_under_500ms(tmp_path):
    t0 = time.time()
    for _ in range(20):
        check_path(tmp_path, "write")
    assert (time.time() - t0) / 20 < 0.5  # 요구사항9절: 500ms 이내
