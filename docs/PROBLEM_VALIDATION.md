# Problem selection and validation

Research snapshot: 2026-10-10. Searches covered arXiv, PubMed, GitHub repositories/issues/discussions, Hacker News, and Reddit. Search results from r/MedicalAI and Hacker News did not surface sufficiently specific first-hand discussions for direct evidence in this snapshot; the validation below uses source-readable MONAI discussions/issues and a current medical-imaging benchmark preprint. The preprint is not peer reviewed.

## Five recurring problems

| Pain point | Who encounters it | Existing approaches and remaining gap |
|---|---|---|
| Patient, study, or acquisition leakage and unstable splits | Imaging ML researchers preparing slice, patch, or longitudinal cohorts | MONAI and nnU-Net let users build splits in their training workflow; the split semantics and source-patient linkage remain pipeline-specific. A standalone manifest audit can catch cross-split patient IDs and exact hashes before training. |
| Internal metrics fail to transfer to external sites | Clinical researchers and hospital AI validation teams | External test cohorts and challenge datasets exist, but access and protocol harmonization are difficult. A systematic review found performance decreases in 70/86 externally evaluated radiology algorithms. CohortSeal can identify and construct one site holdout, but cannot obtain independent cohorts or validate clinical utility. |
| Reproduction of reported medical imaging methods is incomplete | Research engineers reproducing published models | Checklists improve reporting, while execution still requires custom data, split, preprocessing, and evaluation glue. A systematic review specifically describes gaps in reproducibility-focused reporting. |
| DICOM de-identification quality is difficult to measure consistently | Imaging informatics teams sharing research data | De-identification tools exist, but verifying that identifiers are removed while DICOM remains useful and valid is separate work. Recent work proposes a synthetic-PHI DICOM benchmark, showing evaluation is itself a distinct task. |
| Deployed model drift and unclear response ownership | Hospital ML platform and clinical safety teams | Monitoring frameworks define useful integrity, performance, and impact categories. Local collection, review cadence, and escalation remain institution-specific operational work. |

Sources: [MONAI patch handling issue](https://github.com/Project-MONAI/MONAI/issues/7641), [MONAI Label validation discussion](https://github.com/Project-MONAI/MONAILabel/discussions/1718), [MONAI LUNA16 split discussion](https://github.com/Project-MONAI/tutorials/discussions/1582), [external-validation systematic review](https://pubmed.ncbi.nlm.nih.gov/35652114/), [reproducibility systematic review](https://pubmed.ncbi.nlm.nih.gov/37407841/), [synthetic-PHI DICOM benchmark preprint](https://arxiv.org/abs/2508.01889), and [health-care monitoring framework preprint](https://arxiv.org/abs/2512.09048).

## Selected problem

Build CohortSeal for patient-aware medical-image manifest auditing and reproducible split creation. Slice, patch, series, and repeated-visit cohorts make patient-level grouping easy to lose between dataset preparation and model training. MONAI Label exposes configurable validation partitioning, and nnU-Net supports explicit splits, but neither is intended as a general, independent manifest audit and run ledger across arbitrary imaging pipelines.

## Practitioner discussion evidence

1. In [MONAI Label discussion #1718](https://github.com/Project-MONAI/MONAILabel/discussions/1718), a user asks whether validation is constant and leakage-safe: “does the software automatically make a constant validation set that ensures no data leakage affecting the validation accuracy?” The maintainer reply explains that the default random split is recreated when training is triggered again, so prior validation cases may move into training.
2. In [MONAI issue #7641](https://github.com/Project-MONAI/MONAI/issues/7641), a researcher says they need to split medical imaging into patches “before separating the training and validation datasets,” then manually flatten and reconstruct the dataset. This is a concrete point where patch-level operations can sever the patient grouping needed for safe splits.
3. In [MONAI tutorials discussion #1582](https://github.com/Project-MONAI/tutorials/discussions/1582), a contributor reports that “healthy subjects were inadvertently omitted from our data splits” and says the split files and metrics would be corrected. That demonstrates how list-construction errors can alter evaluation cohorts.

## Closest solutions and gaps

**Closest workflow components:** MONAI Label's `partition_datalist` and nnU-Net's `splits_final.json`/manual data split workflow.

1. They are integrated into a training or annotation workflow; neither is a generic preflight auditor across manifests from MONAI, nnU-Net, custom PyTorch, or other pipelines.
2. User-supplied case identifiers and split construction do not alone verify that multiple patches, studies, or series for one patient stayed together.
3. Neither tool is positioned as a persistent, independent integrity ledger that combines split overlap, optional exact duplicate hashes, and a shareable report.

These are product-scope gaps, not claims that the frameworks lack configurable splitting. MONAI Label explicitly supports a custom validation datalist; CohortSeal focuses on making split assumptions inspectable outside a particular training loop.

## Success statement

If CohortSeal works, users will be able to validate a CSV/JSON cohort for patient and exact-hash split overlap and write a reproducible patient-grouped split in under five minutes instead of hand-inspecting split files and debugging leakage only after model metrics look suspicious.

## Scope inference

The cited evidence supports problems around split stability, patch handling, and data-list integrity. The proposed general preflight tool is an inference from those workflows and the limitations of training-specific split utilities. It is not a claim that a passing CohortSeal audit demonstrates clinical generalization.
