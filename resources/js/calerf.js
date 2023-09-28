
// ANY REAL ARGUMENT
function erf( x ){
    return calerf( x, 0 );
}
// ABS(X) .LT. XBIG
function erfc( x ){
    return calerf( x, 1 );
}
// XNEG .LT. X .LT. XMAX
function erfcx( x ){
    return calerf( x, 2 );
}


// C------------------------------------------------------------------
// C Coefficients for approximation to erf in first interval
// C------------------------------------------------------------------
const ERF_A = [ 3.16112374387056560E00, 1.13864154151050156E02, 3.77485237685302021E02,        3.20937758913846947E03, 1.85777706184603153E-1 ];
const ERF_B = [ 2.36012909523441209E01, 2.44024637934444173E02, 1.28261652607737228E03,       2.84423683343917062E03 ];

// C------------------------------------------------------------------
// C Coefficients for approximation to erfc in second interval
// C------------------------------------------------------------------
const ERF_C = [ 5.64188496988670089E-1, 8.88314979438837594E0, 6.61191906371416295E01,        2.98635138197400131E02, 8.81952221241769090E02, 1.71204761263407058E03, 2.05107837782607147E03,        1.23033935479799725E03, 2.15311535474403846E-8 ];
const ERF_D = [ 1.57449261107098347E01, 1.17693950891312499E02, 5.37181101862009858E02,        1.62138957456669019E03, 3.29079923573345963E03, 4.36261909014324716E03, 3.43936767414372164E03,        1.23033935480374942E03 ];

// C------------------------------------------------------------------
// C Coefficients for approximation to erfc in third interval
// C------------------------------------------------------------------
const ERF_P = [ 3.05326634961232344E-1, 3.60344899949804439E-1, 1.25781726111229246E-1,        1.60837851487422766E-2, 6.58749161529837803E-4, 1.63153871373020978E-2 ];
const ERF_Q = [ 2.56852019228982242E00, 1.87295284992346047E00, 5.27905102951428412E-1,        6.05183413124413191E-2, 2.33520497626869185E-3 ];

const PI_SQRT = Math.sqrt(Math.PI);
const THRESHOLD = 0.46875;

/*
 * ************************************** Hardware dependant constants were
 * calculated on Dell "Dimension 4100": - Pentium III 800 MHz running
 * Microsoft Windows 2000 *************************************
 */
const X_MIN = Double.MIN_VALUE;
const X_INF = Double.MAX_VALUE;
const X_NEG = -9.38241396824444;
const X_SMALL = 1.110223024625156663E-16;
const X_BIG = 9.194E0;
const X_HUGE = 1.0 / (2.0 * Math.sqrt(X_SMALL));
const X_MAX = Math.min(X_INF, 1.0 / (Math.sqrt(Math.PI) * X_MIN));

function calerf( X, jint ){
    /*
	* ****************************************** 
    * ORIGINAL FORTRAN version
	* can be found at: http://www.netlib.org/specfun/erf
	********************************************
	* C------------------------------------------------------------------ C
	* C THIS PACKET COMPUTES THE ERROR AND COMPLEMENTARY ERROR FUNCTIONS C
	* FOR REAL ARGUMENTS ARG. IT CONTAINS TWO FUNCTION TYPE C SUBPROGRAMS,
	* ERF AND ERFC (OR DERF AND DERFC), AND ONE C SUBROUTINE TYPE
	* SUBPROGRAM, CALERF. THE CALLING STATEMENTS C FOR THE PRIMARY ENTRIES
	* ARE C C Y=ERF(X) (OR Y=DERF(X) ) C AND C Y=ERFC(X) (OR Y=DERFC(X) ).
	* C C THE ROUTINE CALERF IS INTENDED FOR INTERNAL PACKET USE ONLY, C
	* ALL COMPUTATIONS WITHIN THE PACKET BEING CONCENTRATED IN THIS C
	* ROUTINE. THE FUNCTION SUBPROGRAMS INVOKE CALERF WITH THE C STATEMENT
	* C CALL CALERF(ARG,RESULT,JINT) C WHERE THE PARAMETER USAGE IS AS
	* FOLLOWS C C FUNCTION PARAMETERS FOR CALERF C CALL ARG RESULT JINT C
	* ERF(ARG) ANY REAL ARGUMENT ERF(ARG) 0 C ERFC(ARG) ABS(ARG) .LT. XMAX
	* ERFC(ARG) 1 C C THE MAIN COMPUTATION EVALUATES NEAR MINIMAX
	* APPROXIMATIONS C FROM
	* "RATIONAL CHEBYSHEV APPROXIMATIONS FOR THE ERROR FUNCTION" C BY W. J.
	* CODY, MATH. COMP., 1969, PP. 631-638. THIS C TRANSPORTABLE PROGRAM
	* USES RATIONAL FUNCTIONS THAT THEORETICALLY C APPROXIMATE ERF(X) AND
	* ERFC(X) TO AT LEAST 18 SIGNIFICANT C DECIMAL DIGITS. THE ACCURACY
	* ACHIEVED DEPENDS ON THE ARITHMETIC C SYSTEM, THE COMPILER, THE
	* INTRINSIC FUNCTIONS, AND PROPER C SELECTION OF THE MACHINE-DEPENDENT
	* CONSTANTS. C C AUTHOR: W. J. CODY C MATHEMATICS AND COMPUTER SCIENCE
	* DIVISION C ARGONNE NATIONAL LABORATORY C ARGONNE, IL 60439 C C LATEST
	* MODIFICATION: JANUARY 8, 1985 C
	* C------------------------------------------------------------------
	*/

	let result = 0.0;
	let Y = Math.abs(X);
	let Y_SQ, X_NUM, X_DEN;
 
	if (Y <= THRESHOLD) {
	    Y_SQ = 0.0;
	    if (Y > X_SMALL) {
	        Y_SQ = Y * Y;
	    }
	    X_NUM = ERF_A[4] * Y_SQ;
	    X_DEN = Y_SQ;
	    for (let i = 0; i < 3; i++) {
	        X_NUM = (X_NUM + ERF_A[i]) * Y_SQ;
	        X_DEN = (X_DEN + ERF_B[i]) * Y_SQ;
	    }
	    result = X * (X_NUM + ERF_A[3]) / (X_DEN + ERF_B[3]);
	    if (jint != 0) {
	        result = 1.0 - result;
	    }
	    if (jint == 2) {
	        result = Math.exp(Y_SQ) * result;
	    }
	    return result;
	} else if (Y <= 4.0) {
	    X_NUM = ERF_C[8] * Y;
	    X_DEN = Y;
	    for (let i = 0; i < 7; i++) {
	        X_NUM = (X_NUM + ERF_C[i]) * Y;
	        X_DEN = (X_DEN + ERF_D[i]) * Y;
	    }
	    result = (X_NUM + ERF_C[7]) / (X_DEN + ERF_D[7]);
	    if (jint != 2) {
	        Y_SQ = Math.round(Y * 16.0) / 16.0;
	        let del = (Y - Y_SQ) * (Y + Y_SQ);
	        result = Math.exp(-Y_SQ * Y_SQ) * Math.exp(-del) * result;
	    }
	} else {
	    result = 0.0;
	    if (Y >= X_BIG && (jint != 2 || Y >= X_MAX)) {
	        ;
	    } else if (Y >= X_BIG && Y >= X_HUGE) {
	        result = PI_SQRT / Y;
	    } else {
	        Y_SQ = 1.0 / (Y * Y);
	        X_NUM = ERF_P[5] * Y_SQ;
	        X_DEN = Y_SQ;
	        for (let i = 0; i < 4; i++) {
		   X_NUM = (X_NUM + ERF_P[i]) * Y_SQ;
	            X_DEN = (X_DEN + ERF_Q[i]) * Y_SQ;
	        }
	        result = Y_SQ * (X_NUM + ERF_P[4]) / (X_DEN + ERF_Q[4]);
	        result = (PI_SQRT - result) / Y;
	        if (jint != 2) {
	            Y_SQ = Math.round(Y * 16.0) / 16.0;
	            let del = (Y - Y_SQ) * (Y + Y_SQ);
	            result = Math.exp(-Y_SQ * Y_SQ) * Math.exp(-del) * result;
	        }
	    }
	}
 
	if (jint == 0) {
	    result = 0.5 - result + 0.5;
	    if (X < 0) {
	        result = -result;
	    }
	} else if (jint == 1) {
	    if (X < 0) {
	        result = 2.0 - result;
	    }
	} else {
	    if (X < 0) {
	        if (X < X_NEG) {
	            result = X_INF;
	        } else {
	            Y_SQ = Math.round(X * 16.0) / 16.0;
	            let del = (X - Y_SQ) * (X + Y_SQ);
	            Y = Math.exp(Y_SQ * Y_SQ) * Math.exp(del);
	            result = Y + Y - result;
	        }
	    }
	}
	return result;
}