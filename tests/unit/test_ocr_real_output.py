"""Unit tests verifying OCR text normalization and entity parsing against real-world packaging text.

Dataset source: datasets/results/pilot-002/raw/*.json (PB31 blister and box photo scans).
Covers real OCR noise: Vietnamese diacritics, character confusables (O/0, l/1),
registration numbers (VD-, VN-), packaging artifacts, and multi-line layouts.
"""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
import pytest

from drugtime.modules.catalog.application.normalize_ocr import (
    normalize_clean,
    normalize_key,
    normalize_ocr_text,
)
from drugtime.modules.catalog.domain.catalog_index import (
    StrengthStatus,
)


REAL_OCR_SAMPLES = {
    "atorvastatin_10_box_001": {
        "image_id": "atorvastatin_10_box_001",
        "json_filename": "06f91517-adb5-4f5d-906f-f68c1e5d2cdf.json",
        "packaging": "box",
        "raw_text": 'R THUOC Kt 0ON\nGMP WHO\nATATORVASTATIN 10 mg\nAtorvastatin 10 mg\n(Duới dạng Atorvastatin calci trihydrat)\nHỌP 3 VĨ x 10 VIÊN NÊN BAO PHIM\ncÔNG TY CO PHAN DƯỢC PHAM AN TNIÊN\nAS 314 Bog Sao hng 5,Quan 8TP C in',
        "expected_strengths": ['10 mg'],
    },
    "metformin_500_blister_001": {
        "image_id": "metformin_500_blister_001",
        "json_filename": "e7a80d6a-3cbe-4890-b07a-cfc29bc7e9a1.json",
        "packaging": "blister",
        "raw_text": 'Vetlornin ydrocloid\nMetform\nTIPHARCO\nMetonin bydroclorid 5\nea byeocisót 500mg\nMetformin\nMetformi\nSDK: VD-13882-11\nSEK: VD-13882-11\nMeformin bydesck\nMelrmit bydeocoeid 500mg\nda yaand 50Omg\nMetformin\nMetformin\nMe.\nTPHARCO\nG2-WHO\nMetormin bydoco,\nSmg\nMedimia bydnstid 500mg\nMetformin\nMetformin Met.\nSDK VD-1388-11\ndma bynint 500mg\nMetfornin bydrock.\nMetformin\nMet.\nMecrmia bydck\n1 Met.',
        "expected_strengths": ['500 mg'],
    },
    "candesartan_htz_32_25_box_001": {
        "image_id": "candesartan_htz_32_25_box_001",
        "json_filename": "3e2b29bd-ee6f-44b2-8470-7b9a9bf0bcb0.json",
        "packaging": "box",
        "raw_text": 'THUỐC BIỆT DUỢC\nTHUỐC BIỆT DUỢC OMP WHo\nACANDESARTAN HTZ 32-25\nVIÊN NÉN\nCandesartan cilexetil 32 mg\nHydrochlorothiazide 25 mg Hộp 3 vi x 10 viên\ncONG TY CÓ PHAN DƯỢc PHAM AN THIÊN\nu 24 6g Saa, Phưong s Ougn 8, TP. HỒ Chi Meh',
        "expected_strengths": ['32 mg', '25 mg'],
    },
    "bisoprolol_2_point_5_box_002": {
        "image_id": "bisoprolol_2_point_5_box_002",
        "json_filename": "2da6ca63-2bff-4b87-95f3-959067784a05.json",
        "packaging": "box",
        "raw_text": 'AT Bisoproloi 2.B-\nBisoprolounarate\nR\nA\nPRESCRIPTION DRUG\nAT Bisoprolol2.5-+\ntAT Bisoprolol Fumarate\n2.5 mg\nBox of 10 blisters 1t\nAN TEN a\nANE 34 Bng Se',
        "expected_strengths": ['2.5 mg'],
    },
    "efferalgan_blister_002": {
        "image_id": "efferalgan_blister_002",
        "json_filename": "35596a5b-074c-416d-a2c5-e3f748adb9aa.json",
        "packaging": "blister",
        "raw_text": 'RALGAN ERALEA\n500 ma\nVESCENTI\nESCENT\nUPSA SAS FANCE\nRVESCENT\ntFFERVE\nFFERYE\nWAGHAOL\nUERIME\nSRVESCENT I\nFRrERYESCENT\nERALGAN EFERALGAN\nSOMPRINA\n500 Ng\nAFERVESOENT\n500 rng\nRAL\nLGANS',
        "expected_strengths": [],
    },
    "metformin_500_blister_002": {
        "image_id": "metformin_500_blister_002",
        "json_filename": "07a91d95-ea4b-4cfa-b360-a2b42c0d39de.json",
        "packaging": "blister",
        "raw_text": 'Smg\nWARM\nformin 500mg\nTV.PHARM\nMetformin 500mg\nMettormin.HCI 5o0mg\nMetformin\n8mg\nFMetformin 500mg\nsooma\nTVPHARM\nMottormin.HCI S0Omg\n00mg\nMettarmin 500mg\nattormin HCI 500P\nformin 50Omg\nMettomn CIOomg\nMetformin 50Omg\nMotformin HCI500mg\nMote\nmin 500me\nCTY CPDP TV.PHARN\nMetformin 500mg\nMetformin.HCI 500mg\nMetforg\nMetformin 50Omg\nMetf\nCTYÇ\nMettotL\nTV.PHARM\nMetforp\nMett\nM',
        "expected_strengths": ['500 mg', '8 mg'],
    },
    "tiffy_dey_blister_002": {
        "image_id": "tiffy_dey_blister_002",
        "json_filename": "36aab102-d3ae-4fd6-9902-2870f087a5a2.json",
        "packaging": "blister",
        "raw_text": 'NOCATION\nTABLETS\nPARADETAWL\nCHORPHENRAMINE ALEAIE2 ng\n500 90\nTIFFYDEY\n10 4n9\nStrip of 4 Tablets',
        "expected_strengths": [],
    },
    "strepsils_blister_001": {
        "image_id": "strepsils_blister_001",
        "json_filename": "7da78f76-0b14-4a57-9642-1b5bd7c902f7.json",
        "packaging": "blister",
        "raw_text": 'STREPSILS\nORIGINAL\nLOT ABK9947\nEXP 30 06 29',
        "expected_strengths": [],
    },
    "decolgen_forte_box_002": {
        "image_id": "decolgen_forte_box_002",
        "json_filename": "8d81e335-9dc0-4df6-9051-c73abf139f27.json",
        "packaging": "box",
        "raw_text": 'Decolger\nVIÊN 3 LổP\nFOR TE\nTRỊ CÁC TRIỆU CHỦNG CAM\nR\nKMUC OẤu, HẢT HEL, so MIL NGNET AMUL, BAL SUY',
        "expected_strengths": [],
    },
    "metformin_500_box_003": {
        "image_id": "metformin_500_box_003",
        "json_filename": "37336c67-2a7d-49ff-819c-e7324e8c254b.json",
        "packaging": "box",
        "raw_text": 'Box of 4 blisters of 15 film-coated tablets- 10\nMetformin\n500mg\nTIPHARcO PHAR4CEUTICA ONT SoCK CONPAY',
        "expected_strengths": ['500 mg'],
    },
    "atorvastatin_10_blister_001": {
        "image_id": "atorvastatin_10_blister_001",
        "json_filename": "7134a04f-fc31-41fb-bd01-227c95a2b108.json",
        "packaging": "blister",
        "raw_text": '009orvasla\n10ALOTNasta\nAlaris10mg Alais 10 mg Atotis l0\nAtorvastalin Alorvas)\nAforis\nAlaris 10 mg\nAtorvastatin Alovastatin Alorvastatin Ain\nAlots 10 mgAlotis\nAlorvastatin\nAlaris 10 ma\nAlori\natir. Alovastatin Alorvastatin\nteris 10 mg Aloris 0 mg\nAt\nvastatin Alorvastatin Atorvastatin Atorva\n10 mg Atoris 10 mg Aloris 10 mgAto.\nAlot\nAloris 10 mg\nAloris 1u\nAlorvastatin Alorvastatirn\natin',
        "expected_strengths": ['10 mg'],
    },
    "candesartan_htz_32_25_blister_001": {
        "image_id": "candesartan_htz_32_25_blister_001",
        "json_filename": "10f8e81e-003f-4009-8bc5-f91f15cf37d9.json",
        "packaging": "blister",
        "raw_text": 'alamy\nCandesarian cilexetil\nalamy\ntablets\nCandessrtan Krko 16 mg\nK KRKA\nCandesartan cilexetil\ntablets\nCandesarton\nKrka 16 mg\nKPKA\nCandesartan cilexetil\ntablets\nCandesarton Krka 16 mg\nKKRKA\nCandesartan cilexetil\ntablets\nCandesartan Krka 16 mg\nR\nKRKA\nCandesartan cilexetil\nfablets\nCandesartan Krka 16 sng\ne ID: PTCR3\nwww.alamy.com',
        "expected_strengths": ['16 mg'],
    },
}


def _find_dataset_raw_dir() -> Path | None:
    """Locate datasets/results/pilot-002/raw from repo root or backend workdir."""
    candidates = [
        Path("datasets/results/pilot-002/raw"),
        Path("../datasets/results/pilot-002/raw"),
        Path("../../datasets/results/pilot-002/raw"),
    ]
    for c in candidates:
        if c.is_dir():
            return c.resolve()
    return None


def test_ac1_fixtures_match_source_raw_json_byte_for_byte():
    """Verify that all 12 test fixtures match rawText from the source dataset JSON files
    byte-for-byte, ensuring 100% fidelity to real-world OCR engine output."""
    raw_dir = _find_dataset_raw_dir()
    if raw_dir is None:
        pytest.skip("Dataset raw directory not found (running in detached/isolated package)")

    assert len(REAL_OCR_SAMPLES) >= 10, "Requirement expects at least 10 real OCR samples"

    for sample_id, sample in REAL_OCR_SAMPLES.items():
        json_path = raw_dir / sample["json_filename"]
        assert json_path.is_file(), f"Source JSON file missing: {json_path}"
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("imageId") == sample_id
        assert data.get("rawText") == sample["raw_text"], (
            f"Fixture rawText for {sample_id} does not match source JSON {sample['json_filename']} byte-for-byte"
        )


def test_ac1_normalize_real_blister_and_box_samples_integrity():
    """AC1: All real OCR samples parse through normalize_ocr_text without exceptions,
    preserving lines, text offsets, and generating frozen immutable structures."""
    for sample_id, sample_data in REAL_OCR_SAMPLES.items():
        raw = sample_data["raw_text"]
        doc = normalize_ocr_text(raw)

        # 1. Structural integrity
        assert doc.raw_text == raw, f"Sample {sample_id} modified raw_text"
        assert len(doc.lines) > 0, f"Sample {sample_id} yielded no lines"
        assert "".join(line.raw + line.line_ending for line in doc.lines) == raw

        # 2. Line offset and coordinates consistency
        for line in doc.lines:
            assert raw[line.raw_start : line.raw_end] == line.raw
            assert normalize_clean(line.clean) == line.clean
            assert normalize_key(line.key) == line.key

        # 3. Immutability guarantee
        with pytest.raises(FrozenInstanceError):
            doc.lines[0].key = "mutated_value"


def test_ac2_registration_numbers_filtered_and_not_parsed_as_strengths():
    """AC2: Vietnamese drug registration numbers (SDK: VD-..., VN-...) are identified
    in removed_spans with reason 'registration' and never mistakenly parsed as strengths."""
    blister_sample = REAL_OCR_SAMPLES["metformin_500_blister_001"]
    doc = normalize_ocr_text(blister_sample["raw_text"])

    registration_found = False
    for line in doc.lines:
        for span in line.removed_spans:
            if span.reason == "registration":
                registration_found = True
                assert "vd-" in span.source_text.lower() or "sdk" in span.source_text.lower()
                assert not any(s.source_text == span.source_text for s in line.strengths)

    assert registration_found, "Registration number VD-13882-11 must be detected and filtered"

    # Line 8 has 'SDK: VD-13882-11' -> strengths must be empty
    line_8 = doc.lines[7]
    assert "sdk: vd-13882-11" in line_8.key
    assert len(line_8.strengths) == 0
    assert any(s.reason == "registration" for s in line_8.removed_spans)

    # Line 23 has 'SDK VD-1388-11' -> strengths must be empty
    line_23 = doc.lines[22]
    assert "sdk vd-1388-11" in line_23.key
    assert len(line_23.strengths) == 0
    assert any(s.reason == "registration" for s in line_23.removed_spans)


def test_ac3_conservative_strength_handling_on_confusables():
    """AC3: Scanner noise with character confusables (5o0mg, 50Omg, Atotis l0, 500 ma)
    is handled conservatively: flagged as unparsed/unknown or ignored, never parsed as valid."""
    # 1. Metformin blister with '50Omg' (capital O)
    doc_blister = normalize_ocr_text(REAL_OCR_SAMPLES["metformin_500_blister_001"]["raw_text"])
    line_50o = next(line for line in doc_blister.lines if "50omg" in line.key)
    assert len(line_50o.strengths) == 0, "'50Omg' must not be parsed as valid strength"
    assert len(line_50o.unparsed_strengths) > 0, "'50Omg' should be recognized as amount-like unparsed"
    assert line_50o.unparsed_strengths[0].status == StrengthStatus.UNPARSED

    # 2. Metformin blister 002 with '5o0mg' (lower o)
    doc_blister_2 = normalize_ocr_text(REAL_OCR_SAMPLES["metformin_500_blister_002"]["raw_text"])
    line_5o0 = next(line for line in doc_blister_2.lines if "5o0mg" in line.key)
    assert len(line_5o0.strengths) == 0, "'5o0mg' must not be parsed as valid strength"
    assert len(line_5o0.unparsed_strengths) > 0
    assert line_5o0.unparsed_strengths[0].status == StrengthStatus.UNPARSED

    # 3. Efferalgan blister with '500 ma' (typo unit ma)
    doc_efferalgan = normalize_ocr_text(REAL_OCR_SAMPLES["efferalgan_blister_002"]["raw_text"])
    line_ma = doc_efferalgan.lines[1]
    assert "500 ma" in line_ma.raw
    assert not any(s.canonical == "500 ma" for s in line_ma.strengths)

    # 4. Atorvastatin blister with 'Atotis l0' (confusable letter l)
    doc_atoris = normalize_ocr_text(REAL_OCR_SAMPLES["atorvastatin_10_blister_001"]["raw_text"])
    line_l0 = next(line for line in doc_atoris.lines if "atotis l0" in line.key)
    # The line contains 'Alais 10 mg' which has valid '10 mg', but 'l0' must never be parsed as strength
    assert not any("l0" in s.source_text for s in line_l0.strengths)
    assert not any("l0" in s.canonical for s in line_l0.strengths)


def test_ac3_valid_strength_extraction_on_real_samples():
    """AC3: Verified standard packaging strengths (10 mg, 500 mg, 8 mg, 16 mg, 2.5 mg)
    are accurately extracted into canonical formatted strengths."""
    for sample_id, sample_data in REAL_OCR_SAMPLES.items():
        expected_strengths = sample_data["expected_strengths"]
        doc = normalize_ocr_text(sample_data["raw_text"])

        extracted = set()
        for line in doc.lines:
            for s in line.strengths:
                if s.canonical:
                    extracted.add(s.canonical)

        for expected in expected_strengths:
            assert expected in extracted, (
                f"Sample {sample_id} failed to extract expected strength '{expected}'. "
                f"Extracted: {extracted}"
            )


def test_ac4_vietnamese_diacritic_removal_and_normalization():
    """AC4: Vietnamese pharmaceutical text containing various diacritics and casing
    is cleanly folded into lower-case ASCII search keys without data loss."""
    # Test case 1: Decolgen with full Vietnamese diacritics
    decolgen = REAL_OCR_SAMPLES["decolgen_forte_box_002"]
    doc_decolgen = normalize_ocr_text(decolgen["raw_text"])
    line_symptoms = doc_decolgen.lines[3]
    assert line_symptoms.raw == "TRỊ CÁC TRIỆU CHỦNG CAM"
    assert line_symptoms.clean == "trị các triệu chủng cam"
    assert line_symptoms.key == "tri cac trieu chung cam"

    # Test case 2: Candesartan box with Vietnamese diacritics and Đ/đ
    candesartan = REAL_OCR_SAMPLES["candesartan_htz_32_25_box_001"]
    doc_cande = normalize_ocr_text(candesartan["raw_text"])
    line_thuoc = doc_cande.lines[0]
    assert line_thuoc.raw == "THUỐC BIỆT DUỢC"
    assert line_thuoc.clean == "thuốc biệt duợc"
    assert line_thuoc.key == "thuoc biet duoc"

    # Test case 3: Address line with 'Đ' folded to 'd'
    raw_addr = "Đường Bông Sao, Phường 5, Quận 8, Thành phố Hồ Chí Minh"
    assert normalize_key(raw_addr) == "duong bong sao, phuong 5, quan 8, thanh pho ho chi minh"


def test_packaging_span_removal_on_real_samples():
    """Verify that common packaging noise (hop ... vi, ... vien) is recognized
    as packaging metadata in removed_spans."""
    cande_sample = REAL_OCR_SAMPLES["candesartan_htz_32_25_box_001"]
    doc = normalize_ocr_text(cande_sample["raw_text"])
    # Line 6: 'Hydrochlorothiazide 25 mg Hộp 3 vi x 10 viên'
    line_pack = doc.lines[5]
    assert "Hộp 3 vi x 10 viên" in line_pack.raw

    reasons = [r.reason for r in line_pack.removed_spans]
    assert "packaging" in reasons, "Expected packaging reason in removed spans"


def test_lot_and_expiry_numbers_not_falsely_extracted_as_strengths():
    """Verify that LOT and EXP date numbers (e.g., 'LOT ABK9947 EXP 30 06 29')
    are not falsely extracted as medication strengths."""
    strepsils = REAL_OCR_SAMPLES["strepsils_blister_001"]
    doc = normalize_ocr_text(strepsils["raw_text"])
    line_lot = doc.lines[2]
    assert line_lot.raw == "LOT ABK9947"
    assert len(line_lot.strengths) == 0

    line_exp = doc.lines[3]
    assert line_exp.raw == "EXP 30 06 29"
    assert len(line_exp.strengths) == 0
