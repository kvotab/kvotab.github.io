## 2.2 Silo model corrections

The Silo, a cylindrical vault for intermediate-level waste in SFR1, is represented as five vertical sections (ID_1 through ID_5). Each section contains inner and outer waste domains, separated by an inner wall and enclosed by a concrete wall and bentonite barrier. The corrections described below address identified deficiencies in the Silo formulation.

Equivalent corrections are applied to the corresponding fracture-flow transfers.

### 2.2.1 Internal water flow

For each section (i = 1 to 5), the transfer from the inner waste grout to the inner wall is corrected to use the sum of the four lateral outward flows from the inner region:

`switch_flow*(flowOut[0i_Inner_y+]+flowOut[0i_Inner_x+]+flowOut[0i_Inner_y-]+flowOut[0i_Inner_x-])`

### 2.2.2 Bottom bentonite outflow

The transfer from the bottom sand-bentonite compartment to the geosphere sink is corrected to include all outward flows from the bottom bentonite region. This includes lateral flows in all eight horizontal directions and downward z-direction flows from the bottom bentonite region, for a total of 17 flow-path contributions.

### 2.2.3 Top gravel outflow

The transfer from the top gravel compartment to the geosphere sink is set to:

`switch_flow*(flowOut[TopGravel_z+]+flowOut[TopGravel_horizontal_outward])`

This formulation captures both upward and horizontal outward flow components.

### 2.2.4 Grout volume adjustment

The volume of the inner grout compartment in each section is adjusted by subtracting the volume occupied by the waste packages (Drum_Ce waste, CM_Ce waste, and mould) located within the grout. These waste types were introduced in an input-data update, but the corresponding grout-volume expression was not updated at that time.

### 2.2.5 Resulting radionuclide releases

This section presents radionuclide release rates from simulations with the corrected Silo base-case model and compares them with results from the uncorrected base-case variant to quantify the effect of the corrections on near-field releases.

Figure 1 shows near-field radionuclide release rates from the Silo for the corrected model (thick lines) and the uncorrected model (thin lines). Values in parentheses indicate the ratio of the maximum release rate in the corrected model to that in the uncorrected model.

*Figure 1. Near-field radionuclide release rates from the Silo for the corrected model (thick lines) and the uncorrected base case (thin lines). Values in parentheses show the ratio of the maximum release rate in the corrected model to that in the uncorrected model.*
