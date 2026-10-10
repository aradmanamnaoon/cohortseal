# Design decision: patient is the indivisible split unit

Many computer-vision utilities split rows because they do not know which examples share a subject. CohortSeal requires an explicit patient group and assigns every row in that group together. This can reduce the nominal number of independent samples and make class balance less tidy, but leakage of repeated anatomy or acquisition context answers an easier question than generalization to unseen patients.

This does not imply that patient-level separation is sufficient for clinical validity. Site, scanner, time, and protocol shifts can remain. A site holdout makes one such evaluation explicit, while external validation design remains with the study team.
