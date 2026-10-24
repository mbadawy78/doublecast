"""Folders through Doublecast: scrambled names and contents, no copies, locked to allowed places."""

import pytest
from openpyxl import Workbook

from doublecast.gateway import Gateway, allow, allowed, disallow


def _place(tmp_path):
    root = tmp_path / "Downloads"
    deal = root / "Nordia Hellas deal"
    (deal / "Project Falcon").mkdir(parents=True)
    (deal / "notes.md").write_text("Call Eleni Papadopoulou about Nordia Hellas pricing.\n", encoding="utf-8")
    (deal / "Project Falcon" / "Kallergis_offer.csv").write_text(
        "Customer,Contact,Revenue\nKallergis,Georgios Andreou,1250.00\n", encoding="utf-8"
    )
    wb = Workbook()
    wb.active.append(["Customer", "Revenue"])
    wb.active.append(["Nordia Hellas", 1000])
    wb.save(deal / "sales.xlsx")
    (deal / "photo.jpg").write_bytes(b"\xff\xd8")
    secret = tmp_path / "Private"
    secret.mkdir()
    (secret / "x.md").write_text("Eleni Papadopoulou", encoding="utf-8")
    return root, deal, secret


SECRETS = ("Nordia", "Kallergis", "Falcon", "Eleni", "Papadopoulou", "Andreou", "1250")


def test_list_search_read_show_no_real_names(engine, tmp_path):
    root, deal, _ = _place(tmp_path)
    before = sorted(p for p in root.rglob("*"))
    g = Gateway(engine, [root])
    listing = g.list_folder("Nordia Hellas deal", depth=3)
    body = listing.split("\n", 0)[0].replace("Nordia Hellas deal/", "")  # the name the user typed is theirs
    for s in SECRETS:
        assert s not in body, s
    assert "photo.jpg" not in listing and "not shown" in listing
    csv_path = next(line.split("  (")[0] for line in listing.splitlines() if line.split("  (")[0].endswith(".csv"))
    text = g.read(csv_path)
    assert "Customer,Contact,Revenue" in text and not any(s in text for s in SECRETS)
    xlsx = g.read("Nordia Hellas deal/sales.xlsx")
    assert "Sheet" in xlsx and "Nordia" not in xlsx
    found = g.search("Nordia Hellas deal", "Papadopoulou")
    assert "notes" in found and "Papadopoulou" not in found
    # nothing was copied or written anywhere in the user's places
    assert sorted(p for p in root.rglob("*")) == before


def test_locked_to_allowed_places(engine, tmp_path):
    root, _, secret = _place(tmp_path)
    g = Gateway(engine, [root])
    with pytest.raises(PermissionError):
        g.read(str(secret / "x.md"))
    with pytest.raises(PermissionError):
        g.list_folder(str(root / ".." / "Private"))
    with pytest.raises(PermissionError):
        Gateway(engine, []).list_folder(str(root))


def test_save_puts_real_values_back_and_backs_up(engine, tmp_path):
    root, deal, _ = _place(tmp_path)
    g = Gateway(engine, [root])
    listing = g.list_folder("Nordia Hellas deal", depth=2)
    sub = next(line[:-1] for line in listing.splitlines() if line.endswith("/"))
    org = engine.scramble("Nordia Hellas").text
    assert g.write(f"{sub}/summary.md", f"{org} is the biggest customer.").startswith("Saved")
    assert (deal / "Project Falcon" / "summary.md").read_text(encoding="utf-8") == (
        "Nordia Hellas is the biggest customer."
    )
    with pytest.raises(FileExistsError):
        g.write(f"{sub}/summary.md", "again")
    g.write(f"{sub}/summary.md", "again", overwrite=True)
    assert list((engine.config.home / "backups").rglob("summary.md"))


def test_allow_list(tmp_path):
    folder = tmp_path / "Docs"
    folder.mkdir()
    allow(tmp_path, folder)
    assert allowed(tmp_path) == [folder.resolve()]
    with pytest.raises(ValueError):
        allow(tmp_path, tmp_path.home())
    assert disallow(tmp_path, folder) and allowed(tmp_path) == []
