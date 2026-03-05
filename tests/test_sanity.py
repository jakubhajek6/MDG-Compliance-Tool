import pytest
from unittest.mock import MagicMock, patch

# Základní sanity test pro ověření prostředí

def test_pytest_setup():
    assert True


# ===========================================================================
# modules/podklady.py
# ===========================================================================

class TestLookupSubjektId:
    """Testy pro lookup_subjekt_id()."""

    def test_not_found_empty_html(self):
        """Neexistující IČO – HTML bez subjektId odkazů → None."""
        from modules.podklady import lookup_subjekt_id
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><p>Žádné výsledky.</p></body></html>"
        with patch("modules.podklady.requests.get", return_value=mock_resp):
            result = lookup_subjekt_id("00000001")
        assert result is None

    def test_found(self):
        """Platné IČO – HTML s href obsahujícím subjektId → vrátí string ID."""
        from modules.podklady import lookup_subjekt_id
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = (
            '<html><body>'
            '<a href="/ias/ui/rejstrik-firma.vysledky?subjektId=898776&typ=PLATNY">výsledek</a>'
            '</body></html>'
        )
        with patch("modules.podklady.requests.get", return_value=mock_resp):
            result = lookup_subjekt_id("03999840")
        assert result == "898776"

    def test_http_error_returns_none(self):
        """HTTP 404 → None."""
        from modules.podklady import lookup_subjekt_id
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("modules.podklady.requests.get", return_value=mock_resp):
            result = lookup_subjekt_id("12345678")
        assert result is None

    def test_network_exception_returns_none(self):
        """Síťová výjimka → None (nevyhodí výjimku)."""
        import requests as req
        from modules.podklady import lookup_subjekt_id
        with patch("modules.podklady.requests.get", side_effect=req.RequestException("timeout")):
            result = lookup_subjekt_id("12345678")
        assert result is None


class TestDownloadOrPdf:
    """Testy pro download_or_pdf()."""

    def test_success(self):
        """HTTP 200 + PDF Content-Type + dostatečná velikost → (bytes, 'ok')."""
        from modules.podklady import download_or_pdf, _MIN_PDF_BYTES
        dummy_pdf = b"%PDF-1.4" + b"X" * (_MIN_PDF_BYTES + 100)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = dummy_pdf
        with patch("modules.podklady.requests.get", return_value=mock_resp):
            data, status = download_or_pdf("898776")
        assert status == "ok"
        assert data == dummy_pdf

    def test_http_404(self):
        """HTTP 404 → (None, str obsahující '404')."""
        from modules.podklady import download_or_pdf
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("modules.podklady.requests.get", return_value=mock_resp):
            data, status = download_or_pdf("000000")
        assert data is None
        assert "404" in status

    def test_too_small(self):
        """Odpověď je příliš malá (HTML error stránka) → (None, str)."""
        from modules.podklady import download_or_pdf
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF" + b"X" * 100  # pouze 104 bajtů
        with patch("modules.podklady.requests.get", return_value=mock_resp):
            data, status = download_or_pdf("898776")
        assert data is None
        assert "příliš malý" in status

    def test_wrong_content_type(self):
        """Content-Type není PDF → (None, str)."""
        from modules.podklady import download_or_pdf
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_resp.content = b"<html>error</html>"
        with patch("modules.podklady.requests.get", return_value=mock_resp):
            data, status = download_or_pdf("898776")
        assert data is None
        assert "Content-Type" in status


class TestMakeFilename:
    """Testy pro make_filename()."""

    def test_or_format(self):
        from modules.podklady import make_filename
        from datetime import date
        today = date.today().strftime("%d.%m.%Y")
        fname = make_filename("MatiDal s.r.o.", "or")
        assert fname.endswith(".pdf")
        assert today in fname
        assert "výpis OR" in fname

    def test_esm_format(self):
        from modules.podklady import make_filename
        fname = make_filename("Testovací firma a.s.", "esm")
        assert "ESM" in fname
        assert fname.endswith(".pdf")

    def test_grafika_format(self):
        from modules.podklady import make_filename
        fname = make_filename("Firma", "esm_grafika")
        assert "grafická struktura" in fname

    def test_sanitizes_unsafe_chars(self):
        """Speciální znaky jako / : * ? < > jsou nahrazeny pomlčkou."""
        from modules.podklady import make_filename
        fname = make_filename('Firma/Divize: "speciální"', "or")
        # Žádný ze zakázaných znaků nesmí být v názvu souboru
        for ch in ['/', ':', '"', '*', '?', '<', '>']:
            assert ch not in fname, f"Nebezpečný znak {ch!r} nalezen v: {fname}"


class TestBulkDownloadJs:
    """Testy pro bulk_download_js()."""

    def test_contains_filenames(self):
        """Výstup JS musí obsahovat všechny předané názvy souborů."""
        from modules.podklady import bulk_download_js
        items = [
            {"filename": "Firma_výpis OR_01.01.2026.pdf", "data": b"%PDF" + b"A" * 6000},
            {"filename": "Druha_výpis OR_01.01.2026.pdf", "data": b"%PDF" + b"B" * 6000},
        ]
        js = bulk_download_js(items)
        assert "Firma_výpis OR_01.01.2026.pdf" in js
        assert "Druha_výpis OR_01.01.2026.pdf" in js
        assert "<script>" in js

    def test_empty_list(self):
        """Prázdný seznam → validní HTML bez chyby."""
        from modules.podklady import bulk_download_js
        js = bulk_download_js([])
        assert isinstance(js, str)


# ===========================================================================
# db/database.py – podklady helpers
# ===========================================================================

class TestPodkladyDb:
    """Testy pro DB helpery modulu Podklady – používají dočasnou DB."""

    @pytest.fixture()
    def tmp_db(self, tmp_path, monkeypatch):
        """Přesměruje DB_PATH na dočasný soubor aby testy nezasáhly produkční DB."""
        import db.database as dbmod
        tmp_db_path = tmp_path / "test.sqlite"
        monkeypatch.setattr(dbmod, "DB_PATH", tmp_db_path)
        dbmod.init_db()
        return tmp_db_path

    def test_save_and_get_history(self, tmp_db):
        """save_podklady_run + get_podklady_history pro konkrétní IČO."""
        from db.database import save_podklady_run, get_podklady_history
        run_id = save_podklady_run("03999840", "898776", "MatiDal s.r.o.")
        assert isinstance(run_id, int)
        history = get_podklady_history(ico="03999840")
        assert len(history) == 1
        assert history[0]["ico"] == "03999840"
        assert history[0]["or_status"] == "pending"

    def test_update_status_ok(self, tmp_db):
        """update_podklady_status změní status na 'ok'."""
        from db.database import save_podklady_run, update_podklady_status, get_podklady_history
        run_id = save_podklady_run("12345678", "111", "Test")
        update_podklady_status(run_id, "or_status", "ok")
        history = get_podklady_history(ico="12345678")
        assert history[0]["or_status"] == "ok"

    def test_update_status_invalid_field(self, tmp_db):
        """Nepovolený field → ValueError (ochrana proti SQL injection)."""
        from db.database import save_podklady_run, update_podklady_status
        run_id = save_podklady_run("11111111", "222", "Test")
        with pytest.raises(ValueError, match="Nepovolený field"):
            update_podklady_status(run_id, "DROP TABLE clients--", "ok")

    def test_update_status_invalid_value(self, tmp_db):
        """Nepovolená hodnota → ValueError."""
        from db.database import save_podklady_run, update_podklady_status
        run_id = save_podklady_run("22222222", "333", "Test")
        with pytest.raises(ValueError, match="Nepovolený status"):
            update_podklady_status(run_id, "or_status", "HACKED")

    def test_upsert_client_subjekt_id(self, tmp_db):
        """upsert_client_subjekt_id aktualizuje existujícího klienta."""
        from db.database import add_client, upsert_client_subjekt_id, get_clients
        add_client("03999840", "MatiDal s.r.o.")
        upsert_client_subjekt_id("03999840", "898776")
        clients = get_clients(active_only=False)
        c = next((x for x in clients if x["ico"] == "03999840"), None)
        assert c is not None
        assert c["subjekt_id"] == "898776"
