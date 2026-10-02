# Quantitative Risk Memorandum: Zonal Renewable Buildout & Mix Shift

**To**: Trading Analytics & Executive Risk Committee  
**From**: Senior Quantitative Strategist  
**Date**: December 28, 2025  
**Subject**: Simpson's Paradox & Zonal Degradation Decomposition in Year 3 Shifted Operations  

---

### 1. Executive Summary
During the Year 3 H2 post-shift assessment, executive reviewers may observe that the overall portfolio WMAPE of our candidate forecasting model deteriorated from 0.1361 to 0.1652. A naive interpretation would attribute this deterioration uniformly to general model obsolescence across the Western Interconnection.

However, granular decomposition across zonal delivery hubs (NP15, SP15, ZP26) demonstrates a classic **Simpson's paradox / compositional mix effect**:
1. **Zonal Mix Reallocation**:
   - In pre-shift operations, Central California (ZP26) accounted for only 13% of scheduled delivery volume, while NP15 (North) and SP15 (South) accounted for 42% and 45% respectively.
   - In shifted operations, massive solar buildout in Central California increased ZP26's traded volume share to 25%, while NP15 and SP15 shrank to 37% and 38%.
2. **Within-Zone Degradation**:
   - Within Zone SP15, the candidate model degraded modestly (WMAPE 0.1582), well within normal operational tolerances.
   - Within Zone ZP26, WMAPE rose to 0.1632.
   - Within Zone NP15, WMAPE rose to **0.1740**, directly exceeding the maximum zonal tolerance of 0.170.

### 2. Operational Implication
The model's primary post-shift vulnerability is not distributed evenly: it is acutely localized in **Northern California (NP15)**, where hydro-thermal coordination failed to track volatile evening net-load ramps. In addition, when cross-tabulating zone and regime, the single worst cell in the entire market is **ZP26 under the SPIKE regime (WMAPE = 0.4303)**.
