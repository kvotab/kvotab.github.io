## 2.3 BTF model corrections

The 1–2BTF models represent waste vaults for concrete tanks in SFR1. Each model comprises ten sections (S1 through S10) and discrete North and South end regions. The corrections described below address identified deficiencies in the BTF model formulations.

### 2.3.1 Coordinate direction corrections

The *y*-axis and *x*-axis labels in the flow-path names have been swapped to match the correct physical orientation. This adjustment is required because the COMSOL hydrogeological model and the Ecolego model employ different coordinate conventions. The change is purely one of nomenclature and has no effect on computed results.

### 2.3.2 Missing backfill gravel connections

Advective and diffusive connections between the backfill gravel (`BGravel`) in the end sections and the gravel in the North and South end regions were absent from the base model. The following connections have been added:

- **South end:** a connection between `NearField.SOUTH.gravel1` and `NearField.S1.BGravel`, with flow expressions referencing `flowIn/flowOut[01_BGravel_y-]`.
- **North end:** a connection between `NearField.NORTH.gravel1` and `NearField.S10.BGravel`, with flow expressions referencing `flowIn/flowOut[10_BGravel_y+]`.

Each connection comprises both an advective transfer and a diffusive transfer. The diffusive transfer coefficient is calculated as:

`sw_diff / (0.5 * (RES[source] + RES[target]) * Capacity[source])`

using the longitudinal direction resistance (`res_ldir`).

### 2.3.3 Tunnel gravel flow corrections

The flow expressions for the existing connections between the South and North gravel and the tunnel gravel (`TGravel`) in the end sections have been corrected to reference the appropriate COMSOL flow paths (`flowIn`/`flowOut` for `TGravel` in the *y*-direction).

### 2.3.4 End wall flow corrections

The flow expressions governing transfers through the North and South end walls (wall compartments) and the associated waste compartments have been corrected. All transfers in the chain from waste through wall to gravel, and in the reverse direction, at both the North and South ends are set to reference the correct COMSOL flow paths for the waste domain. For example, `flowOut[10_Waste_y+]` is used for northward outflow from section 10.

### 2.3.5 Dimension corrections

The horizontal dimension (`dim_hdir`) for the North gravel and North wall compartments has been set to the tunnel width (`DIM_TUNNEL_WIDTH`). This corrects an error in the base model in which these compartments were assigned incorrect cross-sectional dimensions.

### 2.3.6 Porosity and volume corrections

The porosity of `GroutBTFBottom` (and of `GroutBTFTop` when using PSAR inventory) has been set equal to the porosity of `Construction_concrete`. For the 1BTF model with PSAR inventory, the following additional corrections have been applied:

- The inner grout (`IGrout`) volume in sections 1–4 has been adjusted to include the waste and tank wall volumes from the Tanks subsystem.
- The waste volume and loading area expressions for tank walls and waste in sections 1–4 have been corrected by replacing the section reference, which incorrectly pointed to S5 or S6, with the actual section number.

### 2.3.7 Resulting radionuclide releases

This section presents radionuclide release rates from simulations with the corrected BTF base-case models and compares them with results from the uncorrected base-case variants to quantify the effect of the corrections on near-field releases.

Figure 4 shows near-field radionuclide release rates from the 1BTF for the corrected model (thick lines) and the uncorrected model (thin lines). Values in parentheses indicate the ratio of the maximum release rate in the corrected model to that in the uncorrected model.

*Figure 4. Near-field radionuclide release rates from 1BTF for the corrected model (thick lines) and the uncorrected base case (thin lines). Values in parentheses show the ratio of the maximum release rate in the corrected model to that in the uncorrected model.*

Figure 5 shows the corresponding results for the 2BTF model.

*Figure 5. Near-field radionuclide release rates from 2BTF for the corrected model (thick lines) and the uncorrected base case (thin lines). Values in parentheses show the ratio of the maximum release rate in the corrected model to that in the uncorrected model.*
