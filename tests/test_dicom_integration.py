"""Optional pydicom checks, using only a fabricated header without pixel data."""

import pytest

pydicom = pytest.importorskip("pydicom")

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from cohortseal.integrations.dicom import DicomInspector


def test_dicom_inspector_flags_tags_without_returning_values(tmp_path):
    """Potential identifiers are reported by keyword and replaced with keyed tokens."""
    target = tmp_path / "patient-secret.dcm"
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    dataset = FileDataset(str(target), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = SecondaryCaptureImageStorage
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.PatientName = "Example^Person"
    dataset.PatientID = "raw-patient-id"
    dataset.Modality = "OT"
    dataset.StudyInstanceUID = generate_uid()
    dataset.SeriesInstanceUID = generate_uid()
    dataset.PatientIdentityRemoved = "NO"
    dataset.save_as(target)
    inspector = DicomInspector(token_key=b"local-test-key-1234567890")
    result = inspector.inspect(target)
    serialized = str(result.to_dict())
    assert "raw-patient-id" not in serialized
    assert "Example^Person" not in serialized
    assert "patient-secret" not in serialized
    assert result.patient_token != "raw-patient-id"
    assert any(item.code == "DICOM_IDENTIFYING_TAG_PRESENT" for item in result.findings)
    record = inspector.to_case_record(result, image_path=target)
    assert record.patient_id == result.patient_token


def test_dicom_inspector_rejects_weak_token_key():
    """Stable HMAC tokenization requires a non-trivial local secret."""
    from cohortseal.integrations.dicom import DicomIntegrationError
    with pytest.raises(ValueError, match="at least 16"):
        DicomInspector(token_key=b"short")
