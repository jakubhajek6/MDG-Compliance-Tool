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


# ===========================================================================
# make_filename – SVG extension for esm_grafika
# ===========================================================================

class TestMakeFilenameSvg:
    """Testy pro make_filename – správná přípona (.pdf vs .svg)."""

    def test_or_has_pdf_extension(self):
        from modules.podklady import make_filename
        name = make_filename("Test s.r.o.", "or")
        assert name.endswith(".pdf")

    def test_esm_has_pdf_extension(self):
        from modules.podklady import make_filename
        name = make_filename("Test s.r.o.", "esm")
        assert name.endswith(".pdf")

    def test_esm_grafika_has_svg_extension(self):
        from modules.podklady import make_filename
        name = make_filename("Test s.r.o.", "esm_grafika")
        assert name.endswith(".svg")
        assert "grafická struktura" in name


# ===========================================================================
# create_renamed_zip
# ===========================================================================

class TestCreateRenamedZip:
    """Testy pro create_renamed_zip()."""

    def test_creates_valid_zip(self):
        import zipfile, io
        from modules.podklady import create_renamed_zip
        files = [
            {"data": b"fake-pdf-content", "filename": "Firma_ESM_05.03.2026.pdf"},
            {"data": b"<svg>fake</svg>", "filename": "Firma_ESM_05.03.2026_grafická struktura.svg"},
        ]
        result = create_renamed_zip(files)
        assert isinstance(result, bytes)
        # Verify it's a valid ZIP
        zf = zipfile.ZipFile(io.BytesIO(result))
        names = zf.namelist()
        assert len(names) == 2
        assert "Firma_ESM_05.03.2026.pdf" in names
        assert "Firma_ESM_05.03.2026_grafická struktura.svg" in names
        assert zf.read("Firma_ESM_05.03.2026.pdf") == b"fake-pdf-content"

    def test_empty_list_returns_valid_empty_zip(self):
        import zipfile, io
        from modules.podklady import create_renamed_zip
        result = create_renamed_zip([])
        assert isinstance(result, bytes)
        zf = zipfile.ZipFile(io.BytesIO(result))
        assert zf.namelist() == []


# ===========================================================================
# match_esm_uploads
# ===========================================================================

class TestMatchEsmUploads:
    """Testy pro match_esm_uploads() – automatické přiřazení souborů."""

    def test_vypis_matched_by_subjekt_id(self):
        """Soubor 'vypis-898776.pdf' se přiřadí k firmě se subjektId 898776."""
        from modules.podklady import match_esm_uploads
        companies = [
            {"nazev": "MatiDal", "ico": "03999840", "subjekt_id": "898776"},
            {"nazev": "Firma B", "ico": "11111111", "subjekt_id": "123456"},
        ]
        result = match_esm_uploads(["vypis-898776.pdf"], companies)
        assert len(result) == 1
        assert result[0]["matched"] is True
        assert result[0]["doc_type"] == "esm"
        assert result[0]["company_idx"] == 0
        assert "MatiDal" in result[0]["new_filename"]

    def test_grafika_matched_by_suffix(self):
        """grafickaStruktura.svg = first company, -2.svg = second company."""
        from modules.podklady import match_esm_uploads
        companies = [
            {"nazev": "Firma A", "ico": "111", "subjekt_id": "100"},
            {"nazev": "Firma B", "ico": "222", "subjekt_id": "200"},
            {"nazev": "Firma C", "ico": "333", "subjekt_id": "300"},
        ]
        names = ["grafickaStruktura.svg", "grafickaStruktura-2.svg", "grafickaStruktura-3.svg"]
        result = match_esm_uploads(names, companies)
        assert all(r["matched"] for r in result)
        assert result[0]["company_idx"] == 0
        assert result[1]["company_idx"] == 1
        assert result[2]["company_idx"] == 2
        assert all(r["doc_type"] == "esm_grafika" for r in result)

    def test_unrecognized_file(self):
        """Nerozpoznaný soubor → matched=False."""
        from modules.podklady import match_esm_uploads
        companies = [{"nazev": "Firma", "ico": "111", "subjekt_id": "100"}]
        result = match_esm_uploads(["random_document.pdf"], companies)
        assert len(result) == 1
        assert result[0]["matched"] is False
        assert result[0]["new_filename"] is None

    def test_mixed_files(self):
        """Mix výpisů, grafik a nerozpoznaných souborů."""
        from modules.podklady import match_esm_uploads
        companies = [
            {"nazev": "MatiDal", "ico": "039", "subjekt_id": "898776"},
            {"nazev": "Easy", "ico": "040", "subjekt_id": "1059250"},
        ]
        names = [
            "vypis-898776.pdf",
            "vypis-1059250.pdf",
            "grafickaStruktura.svg",
            "grafickaStruktura-2.svg",
            "unknown.txt",
        ]
        result = match_esm_uploads(names, companies)
        assert result[0]["matched"] and result[0]["doc_type"] == "esm"
        assert result[1]["matched"] and result[1]["doc_type"] == "esm"
        assert result[2]["matched"] and result[2]["doc_type"] == "esm_grafika"
        assert result[3]["matched"] and result[3]["doc_type"] == "esm_grafika"
        assert not result[4]["matched"]
