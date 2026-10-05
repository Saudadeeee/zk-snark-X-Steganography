# Paper: Covert, Anonymous and Video-Bound Provenance

IEEE conference format (`IEEEtran`), English. `main.pdf` is the compiled paper (14 pages,
extended version; a typical conference limit of 6–8 pages needs trimming, see below).

## Build

```powershell
cd doc/paper
pdflatex main; bibtex main; pdflatex main; pdflatex main
```

Sections live in `sections/*.tex`; references in `references.bib`. Figures in `figures/`
are generated, not drawn:

```powershell
py -3.12 -m benchmark.distortion_experiments_new            # experiments A, B, C (about 40 min)
py -3.12 -m benchmark.distortion_experiments_new --reuse AB # recompute C and the summary only
py -3.12 -m benchmark.distortion_figures_new                # figures/*.pdf from the results
```

## Where the numbers come from

| Paper content | Source |
|---|---|
| Quality, sign statistics, native costs (Tables II, Sec. IX) | `benchmark/results/media_new/20261004T142448Z_1db00a/video_pipeline_new.json` |
| Groth16 / PLONK (Table VI) | `benchmark/results/zkp_new.json` |
| End-to-end stages, attack matrix (Tables VII, VIII) | `benchmark/results/e2e_new.json` |
| Distortion model validation (Tables III–V, Figs. 2–4) | `benchmark/results/distortion_new/` (`summary.json`, CSVs) |
| Worked example (Appendix A) | terminal demo run, block MB 212 / block 5 |

## Before submission

- Fill in authors and affiliation in `main.tex` (placeholders).
- The artifact link in the conclusion points to the GitHub repository; remove it for
  double-blind review.
- Page limits: the Background section (Sec. III) and Appendix A are the natural places to
  shorten; the related-work table and the distortion-model sections carry the contribution.
