"""Mirror folders: scrambled twin, both directions, nothing real leaks into the twin."""

import os

from openpyxl import Workbook, load_workbook

from doublecast.mirror import NOTE, Mirror, register, registered, unregister


def _all_twin_text(twin):
    out = []
    for dirpath, _, files in os.walk(twin):
        for f in files:
            p = os.path.join(dirpath, f)
            out.append(p)
            if p.endswith(".xlsx"):
                wb = load_workbook(p)
                for ws in wb.worksheets:
                    for row in ws.iter_rows(values_only=True):
                        out.extend(str(v) for v in row if v is not None)
            elif not p.endswith((".jpg",)):
                out.append(open(p, encoding="utf-8").read())
    return "\n".join(out)


def _setup(tmp_path):
    real = tmp_path / "work" / "Nordia Hellas deal"
    (real / "Project Falcon").mkdir(parents=True)
    (real / "notes.md").write_text(
        "Call with Eleni Papadopoulou (eleni.p@nordia.gr) about Nordia Hellas pricing.\n", encoding="utf-8"
    )
    (real / "Project Falcon" / "customers.csv").write_text(
        "Customer,Contact,Revenue\nNordia Hellas,Georgios Andreou,1250.00\n", encoding="utf-8"
    )
    wb = Workbook()
    wb.active.append(["Customer", "Margin"])
    wb.active.append(["Kallergis", 0.21])
    wb.save(real / "Kallergis_costing.xlsx")
    (real / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    (real / ".git").mkdir()
    (real / ".git" / "config").write_text("secret", encoding="utf-8")
    return real


def test_twin_holds_no_real_values_and_skips_unreadable_files(engine, tmp_path):
    real = _setup(tmp_path)
    m = Mirror(engine, real)
    assert m.twin.name == "Nordia Hellas deal-AI"
    report = m.sync()
    assert report.scrambled == 3 and report.skipped == {".jpg": 1} and report.failed == 0
    blob = _all_twin_text(m.twin).replace(str(m.twin), "")
    for secret in ("Eleni", "Papadopoulou", "eleni.p@nordia.gr", "Nordia", "Andreou", "Kallergis", "Falcon", "1250"):
        assert secret not in blob, secret
    assert not list(m.twin.rglob("*.jpg")) and not list(m.twin.rglob(".git"))
    assert (m.twin / NOTE).exists()
    # the state with the real names lives in the Doublecast home, not in the twin
    assert m.state_path.parent == engine.config.home / "mirrors"


def test_ai_edit_comes_back_restored(engine, tmp_path):
    real = _setup(tmp_path)
    m = Mirror(engine, real)
    m.sync()
    twin_notes = m.twin / m.state["files"]["notes.md"]["twin"]
    text = twin_notes.read_text(encoding="utf-8")
    double = engine.vault.get("Eleni Papadopoulou")
    assert double and double in text
    twin_notes.write_text(text + f"\nAction: {double} sends the offer.\n", encoding="utf-8")
    report = m.sync()
    assert report.restored == 1
    restored = (real / "notes.md").read_text(encoding="utf-8")
    assert "Action: Eleni Papadopoulou sends the offer." in restored
    assert "eleni.p@nordia.gr" in restored
    # and it does not bounce back and forth
    again = m.sync()
    assert again.scrambled == 0 and again.restored == 0


def test_new_file_from_ai_lands_in_real_folder_with_real_names(engine, tmp_path):
    real = _setup(tmp_path)
    m = Mirror(engine, real)
    m.sync()
    org = engine.vault.get("Nordia Hellas")
    twin_dir = m.twin / m.state["dirs"]["Project Falcon"]
    (twin_dir / f"{org} summary.md").write_text(f"{org} is our biggest customer.", encoding="utf-8")
    m.sync()
    out = real / "Project Falcon" / "Nordia Hellas summary.md"
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "Nordia Hellas is our biggest customer."


def test_both_changed_keeps_both(engine, tmp_path):
    real = _setup(tmp_path)
    m = Mirror(engine, real)
    m.sync()
    twin_notes = m.twin / m.state["files"]["notes.md"]["twin"]
    twin_notes.write_text("AI version", encoding="utf-8")
    (real / "notes.md").write_text("My version, Nordia Hellas.", encoding="utf-8")
    os.utime(real / "notes.md", ns=(1, 1))  # make sure the signature changes
    report = m.sync()
    assert report.conflicts == 1
    assert (real / "notes.md").read_text(encoding="utf-8") == "My version, Nordia Hellas."
    assert (real / "notes (AI).md").read_text(encoding="utf-8") == "AI version"
    assert "Nordia" not in twin_notes.read_text(encoding="utf-8")


def test_real_change_flows_to_twin_and_xlsx_round_trips(engine, tmp_path):
    real = _setup(tmp_path)
    m = Mirror(engine, real)
    m.sync()
    (real / "notes.md").write_text("Georgios Andreou called.", encoding="utf-8")
    assert m.sync().scrambled == 1
    twin_x = m.twin / m.state["files"]["Kallergis_costing.xlsx"]["twin"]
    assert "Kallergis" not in twin_x.name
    wb = load_workbook(twin_x)
    wb.active.append(["New row", 0.3])
    wb.save(twin_x)
    m.sync()
    rows = list(load_workbook(real / "Kallergis_costing.xlsx").active.iter_rows(values_only=True))
    assert rows[1] == ("Kallergis", 0.21)
    # numbers the AI writes into a money column are in its (scaled) world and come back unscaled
    assert rows[2][0] == "New row" and rows[2][1] != 0.3


def test_twin_inside_real_is_refused(engine, tmp_path):
    real = _setup(tmp_path)
    try:
        Mirror(engine, real, real / "inside")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_registry(tmp_path):
    register(tmp_path, tmp_path / "a", tmp_path / "a-AI")
    register(tmp_path, tmp_path / "a", tmp_path / "a-AI")
    assert len(registered(tmp_path)) == 1
    assert unregister(tmp_path, tmp_path / "a") and registered(tmp_path) == []


def test_interrupted_first_sync_leaves_no_copies_in_real_folder(engine, tmp_path):
    real = _setup(tmp_path)
    m = Mirror(engine, real)
    m.twin.mkdir()
    (m.twin / "leftover.md").write_text("half-written by a run that was stopped", encoding="utf-8")
    m.sync()
    m.sync()
    assert not (real / "leftover.md").exists()
    assert not [p for p in real.rglob("*") if "(AI" in p.name]


def test_listed_names_inside_identifiers_and_file_names(engine, tmp_path):
    text = "wb.save('Nordia_Hellas_D365_Items.xlsx')  # Kallergis_costing\n"
    out = engine.scramble(text).text
    assert "Nordia" not in out and "Kallergis" not in out
    assert engine.restore(out) == text
