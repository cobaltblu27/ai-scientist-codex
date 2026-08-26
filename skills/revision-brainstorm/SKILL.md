---
name: revision-brainstorm
description: Generate high-quality research-loop revision and branching strategies from node evidence, critic feedback, and data-insight artifacts.
---

# Revision Brainstorm

<Purpose>
Act as a research-loop revision worker. Diagnose why the current node is insufficient, then propose stronger revise/branch options. Your goal is to offer a direction that will enhance model capability.
</Purpose>

<Inputs>
Use the assigned node idea, research contract, learning notes, node artifacts, critic verdicts, benchmark/split refs, data-insight report, and revision question.
You may also run `data-insight-revision` or cite a fresh matching report, to help you get insight on current pipeline and data. Use them to come up with a better architecture.
</Inputs>

<Task>
Diagnose the bottleneck, then generate distinct revision or branch candidates in proportion to the credible evidence. Recommend one primary action: `revise_same_node`, `branch_from_node`, `abandon_or_reject`, or `escalate`.
</Task>

<Architecture>
For the primary branch, provide an implementation-grade blueprint. Be specific on details. Do not leave placeholders such as "encoder", "router", "predictor head", or "attention" unspecified. Specify implementation options for inputs/provenance, preprocessing, or modules, so worker agent can implement as intended.
</Architecture>

<Candidates>
For each candidate, explain the mechanism change, its evidence or hypothesis, and a discriminating test. Add implementation detail, risks, expected claim, or parent-node provenance where it helps compare or execute the candidate. Branches must differ by mechanism, information source, architecture, objective, or training protocol, not just thresholds or weights.
</Candidates>

<Output>
Write a clear Markdown report covering the bottleneck, credible candidates, and the recommended action. Give the primary candidate an implementation-grade blueprint; keep alternatives concise unless their details affect the choice. Choose the structure and depth that best explain the research decision.
</Output>

Following is an example of how 'revision brainstorming' can be specified. This exact form is not an answer; you may fill in the content of each section freely. 
Examples are extracted from existing works of bioinformatics lab. focus on how they locate a bottleneck, and suggest a breakthrough.
<Examples>
1. Example on DRP prediction framework
Context:
  The model’s goal is to predict how sensitive a cancer cell line will be to a drug, usually measured as log(IC50). Lower IC50 means the cell line is more sensitive to the drug.

  The as-is model uses three main inputs:

  - Basal gene expression: the gene-expression profile of a cancer cell line before drug treatment.
  - Drug representation: a learned embedding of the drug structure, usually from SMILES.
  - Optional condition metadata: dose and treatment duration, when available.

  The model encodes the cell-line expression and drug representation separately, concatenates them, and feeds the result into an MLP to predict drug response. A stronger version first pretrains on LINCS L1000, where the task is to predict post-treatment gene-expression
  changes after a drug is applied, then transfers the learned representation to GDSC IC50 prediction.

  The failing point is that this model treats the drug effect as a single global vector. It can learn that a drug tends to affect certain expression patterns, but it does not explicitly model which genes interact differently under that drug condition.

  This matters because drug response is often driven by pathway-level and gene-network changes, not just independent gene values. The same drug can perturb different gene-gene relationships depending on the cell-line state, dose, and treatment time.

  So the as-is model has a representation gap: it tries to transfer drug-induced transcriptomic knowledge from LINCS to drug sensitivity prediction in GDSC, but it lacks a mechanism for representing condition-specific gene-gene perturbation.

Output:
# Idea: Condition-Specific Gene-Gene Perturbation Attention

  ## Bottleneck Diagnosis

  The current drug response model treats drug effect mostly as a global embedding fused with basal cell-line gene expression. Even if pretrained on LINCS perturbation data, it does not explicitly model how a drug changes gene-gene relationships under a specific cell-line, dose, and time condition.
  This limits mechanism transfer from LINCS to GDSC. The model may learn average drug-response correlations, but it cannot represent condition-specific perturbation structure, which is central to anticancer response.

  ## Enhancement Plan

  ### As-Is

  The model takes basal gene expression, a drug SMILES embedding, and optionally dose/time metadata.

  It encodes:

  - cell-line expression into a cell vector
  - drug structure into a chemical vector
  - dose/time into auxiliary condition vectors

  These are concatenated or fused through an MLP, then used to predict either LINCS perturbed expression during pretraining or GDSC log(IC50) during fine-tuning.

  ### To-Be

  Add a condition-specific gene-gene attention module.

  Instead of representing the drug effect only as a global vector, compute a sample-specific gene interaction matrix conditioned on basal expression, drug embedding, dose, and treatment duration.

  Use this attention matrix as a dynamic perturbation operator for gene-expression prediction. Pretrain it on LINCS perturbation prediction, then transfer the learned perturbation operator into GDSC IC50 prediction.

  ## Implementation Details

  For each sample:

  1. Construct gene-level representations from basal expression.
  2. Encode chemical condition using pretrained molecular embedding plus dose/time projections.
  3. Combine gene and condition representations.
  4. Compute gene-gene self-attention.
  5. Use the attention matrix as the first-layer interaction weights for predicting perturbed gene expression.
  6. During GDSC fine-tuning, reuse the pretrained perturbation module and attach an IC50 prediction head.

  Expected effect:

  - captures drug- and context-specific gene interactions
  - improves transfer from LINCS perturbation data to GDSC response labels
  - gives interpretable gene-pair attention maps
  - helps generalization in drug-blind and disjoint splits

2. Example on patient-level DRP framework:
Context:
  A baseline patient-level drug-response prediction system has been built for oncology. It uses GDSC as the source domain because GDSC has many cancer cell lines with measured drug responses, and uses TCGA as the target patient domain because TCGA has many tumor
  transcriptomes but only sparse treatment-response labels.

  The first version trains a response predictor on GDSC cell-line expression plus drug-response labels. At inference time, it applies the same predictor to TCGA tumor expression to estimate whether a patient is likely to respond to a drug. This works reasonably inside the
  cell-line domain, but performance drops on patient tumors because the input distribution changes from cultured cell lines to bulk tumor tissue.

  A few obvious fixes have already been tried. The team tried direct transfer from GDSC to TCGA, but the model mostly learned cell-line-specific signals. They tried nearest-neighbor matching between a patient tumor and similar GDSC cell lines, but a single matched cell
  line was too crude to represent heterogeneous tumors. They also tried generic domain adaptation to align GDSC and TCGA embeddings, but this risked mixing biologically different cancer types together and weakening tissue-specific structure.

  The current bottleneck is no longer just “make a better drug-response predictor.” The model needs a better patient-transfer mechanism. A TCGA tumor should be represented as a tissue-aware mixture of multiple GDSC cell lines, so the downstream drug-response model can
  still use source-domain pharmacogenomic knowledge while receiving a patient representation that better reflects tumor heterogeneity.

Output:
  # Idea : Tissue-Guided Tumor-to-Cell-Line Aggregation

  ## Bottleneck Diagnosis

  The current model assumes that a patient tumor can be passed directly into a predictor trained on homogeneous cell lines. This creates two linked failures.

  First, there is a source-target domain shift: GDSC cell lines and TCGA tumors have different expression distributions, tissue context, microenvironment effects, and measurement conditions. A predictor that works inside GDSC degrades when directly applied to patients.

  Second, the biological mapping is wrong. A patient tumor is not usually equivalent to a single cell line. It can contain multiple malignant subclones plus non-malignant components. A one-to-one tumor-to-cell-line mapping loses tumor heterogeneity and can align the
  patient to biologically irrelevant source samples.

  A plain domain-adaptation model can reduce source/target separation, but it may over-align the domains and destroy tissue structure. The revised model should not merely make GDSC and TCGA look similar; it should align them while preserving tissue identity and tumor-
  relevant structure.

  ## Enhancement Plan

  ### As-Is

  The current system uses:

  - Source data: GDSC cell-line gene expression and binary drug-response labels.
  - Target data: TCGA tumor gene expression, mostly unlabeled, with sparse labeled patient-drug outcomes for evaluation.
  - Model: a drug-response predictor trained on cell-line drug pairs.
  - Inference: feed TCGA tumor expression directly into the cell-line-trained predictor.
  - Optional existing module: drug/gene perturbation encoder or rank/gene-interaction encoder trained from cell-line or perturbation data.

  The model treats the patient expression vector as if it already lived in the same representation space as the GDSC cell lines.

  ### To-Be

  Add a patient-to-cell-line alignment module before patient inference.

  Represent each patient tumor as an attention-weighted linear combination of many GDSC cell lines, rather than mapping it to one nearest cell line or feeding it directly into the predictor. The attention weights act as a soft decomposition of the tumor into source-domain
  cell-line components.

  Add tissue-level supervision to keep the shared embedding biologically coherent. The alignment module should optimize not only reconstruction, but also tissue-label classification and tissue-cluster compactness. This prevents the model from aligning GDSC and TCGA in a
  way that erases cancer-type structure.

  Then use the aligned patient representation as the patient-side input to the existing drug-response predictor. If the existing predictor uses perturbation-aware or gene-interaction embeddings, apply those modules after alignment so the patient representation is
  compatible with the source-domain response model.

  ## Implementation Details

  Build the revision in two stages.

  Stage 1: alignment module.

  - Input:
      - GDSC expression matrix.
      - TCGA expression matrix.
      - Tissue labels for both domains where available.

  - Train source and target encoders to map cell lines and tumors into a shared latent space.
  - For each TCGA tumor, compute attention weights over all GDSC cell lines.
  - Construct an aligned tumor representation as a weighted sum of GDSC cell-line representations.
  - Train with reconstruction loss so the weighted cell-line mixture can represent the tumor.
  - Add a tissue classifier on latent and/or reconstructed representations.
  - Add center loss or equivalent tissue-clustering regularization so samples from the same tissue type remain close.

  Stage 2: response prediction.

  - Train the drug-response predictor on GDSC cell-line-drug pairs.
  - Use binary GDSC response labels if the patient labels are binary.
  - Concatenate useful response features, for example:
      - aligned expression representation,
      - drug-induced perturbation embedding,
      - drug molecular embedding,
      - rank-based gene interaction embedding.

  - During TCGA inference:
      - pass the patient tumor through the alignment module,
      - convert it into the attention-weighted GDSC-compatible representation,
      - feed that representation into the trained response predictor for each candidate drug.

  Expected validation signals:

  - AUROC/AUPRC improves on held-out TCGA patient-drug labels.
  - Embeddings no longer cluster purely by source domain.
  - Tissue structure is preserved better than generic adversarial alignment.
  - Ablation without attention, tissue classifier, or center loss should reduce performance.
  - The attention weights can be reused as a tumor-heterogeneity interpretation signal.

  The transferable lesson from THERAPI is: when revising a vague GDSC-to-TCGA patient prediction model, do not only add a stronger predictor. First add a biologically constrained transfer mechanism that makes the patient input compatible with the source-domain model.


</Examples>
