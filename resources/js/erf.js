
/* 
 * **************************************************************
 * ERROR FUNCTION (ERF)
 * erf(x) = 2/sqrt(pi) * integral from 0 to x of exp(-t^2) dt
 * 
 * COMPLEMENTARY ERROR FUNCTION (ERFC)
 * erfc(x) = 2/sqrt(pi) * integral from x to inf of exp(-t^2) dt
 *         = 1 - erf(x)
 * 
 * SCALED COMPLEMENTARY ERROR FUNCTION (ERFCX)
 * erfcx(x) = exp(x^2) * erfc(x) ~ (1/sqrt(pi)) * 1/x for large x
 * **************************************************************
 *
 * ************************************** 
 * Hardware dependant constants were
 * calculated on Dell "Dimension 4100": - Pentium III 800 MHz running
 * Microsoft Windows 2000 
 * XMIN   = the smallest positive floating-point number.
 * XINF   = the largest positive finite floating-point number.
 * XNEG   = the largest negative argument acceptable to ERFCX;
 *          the negative of the solution to the equation
 *          2*exp(x*x) = XINF.
 * XSMALL = argument below which erf(x) may be represented by
 *          2*x/sqrt(pi)  and above which  x*x  will not underflow.
 *          A conservative value is the largest machine number X
 *          such that   1.0 + X = 1.0   to machine precision.
 * XBIG   = largest argument acceptable to ERFC;  solution to
 *          the equation:  W(x) * (1-0.5/x**2) = XMIN,  where
 *          W(x) = exp(-x*x)/[x*sqrt(pi)].
 * XHUGE  = argument above which  1.0 - 1/(2*x*x) = 1.0  to
 *          machine precision.  A conservative value is
 *          1/[2*sqrt(XSMALL)]
 * XMAX   = largest acceptable argument to ERFCX; the minimum
 *          of XINF and 1/[sqrt(pi)*XMIN].
 * **************************************
*/
const XMIN = Number.MIN_VALUE;
const XINF = Number.MAX_VALUE;
const XNEG = -9.38241396824444;
const XSMALL = 1.110223024625156663E-16;
const XBIG = 9.194E0;
const XHUGE = 1 / ( 2 * Math.sqrt( XSMALL ) );
const XMAX = Math.min( XINF, 1 / ( Math.sqrt( Math.PI ) * XMIN ) );

// ANY REAL ARGUMENT
function erf( x ){
    if ( Number.isNaN( x ) ) {
		return Number.NaN;
    } else{
        return calerf( x, 0 );
    }
}
// ABS(X) .LT. XBIG
function erfc( x ){
     // Test for domain errors:
	if ( Number.isNaN( x ) || Math.abs( x ) >= XBIG ) {
		return Number.NaN;
	} else {
		return calerf( x, 1 );
	}    
}
// XNEG .LT. X .LT. XMAX
function erfcx( x ){
    // Test for domain errors:
   if ( Number.isNaN( x ) || XNEG > x || x >= XMAX ) {
       return Number.NaN;
   } else {
       return calerf( x, 2 );
   }
}

//------------------------------------------------------------------
// Coefficients for approximation to erf in first interval
//------------------------------------------------------------------
const ERF_A = [ 3.16112374387056560E00, 1.13864154151050156E02, 3.77485237685302021E02, 3.20937758913846947E03, 1.85777706184603153E-1 ];
const ERF_B = [ 2.36012909523441209E01, 2.44024637934444173E02, 1.28261652607737228E03, 2.84423683343917062E03 ];

//------------------------------------------------------------------
// Coefficients for approximation to erfc in second interval
//------------------------------------------------------------------
const ERF_C = [ 5.64188496988670089E-1, 8.88314979438837594E0, 6.61191906371416295E01, 2.98635138197400131E02, 8.81952221241769090E02, 1.71204761263407058E03, 2.05107837782607147E03, 1.23033935479799725E03, 2.15311535474403846E-8 ];
const ERF_D = [ 1.57449261107098347E01, 1.17693950891312499E02, 5.37181101862009858E02, 1.62138957456669019E03, 3.29079923573345963E03, 4.36261909014324716E03, 3.43936767414372164E03, 1.23033935480374942E03 ];

//------------------------------------------------------------------
// Coefficients for approximation to erfc in third interval
//------------------------------------------------------------------
const ERF_P = [ 3.05326634961232344E-1, 3.60344899949804439E-1, 1.25781726111229246E-1, 1.60837851487422766E-2, 6.58749161529837803E-4, 1.63153871373020978E-2 ];
const ERF_Q = [ 2.56852019228982242E00, 1.87295284992346047E00, 5.27905102951428412E-1, 6.05183413124413191E-2, 2.33520497626869185E-3 ];

const SQRTPI = Math.sqrt( Math.PI );
const THRESH = 0.46875;


function calerf( X, jint ){
    /*
	* ****************************************** 
    * ORIGINAL FORTRAN version
	* can be found at: http://www.netlib.org/specfun/erf
	* ********************************************
	* This packet evaluates  erf(x),  erfc(x),  and  exp(x*x)*erfc(x)
	* for a real argument  x.  It contains three FUNCTION type
	* subprograms: ERF, ERFC, and ERFCX (or DERF, DERFC, and DERFCX),
	* and one SUBROUTINE type subprogram, CALERF.  The calling
	* statements for the primary entries are:
	*
	*                 Y=ERF(X)     (or   Y=DERF(X)),
	*
	*                 Y=ERFC(X)    (or   Y=DERFC(X)),
	* and
	*                 Y=ERFCX(X)   (or   Y=DERFCX(X)).
	*
	* The routine  CALERF  is intended for internal packet use only,
	* all computations within the packet being concentrated in this
	* routine.  The function subprograms invoke  CALERF  with the
	* statement
	*
	*        CALL CALERF(ARG,RESULT,JINT)
	*
	* where the parameter usage is as follows
	*
	*    Function                     Parameters for CALERF
	*     call              ARG                  Result          JINT
	*
	*   ERF(ARG)      ANY REAL ARGUMENT         ERF(ARG)          0
	*   ERFC(ARG)     ABS(ARG) .LT. XBIG        ERFC(ARG)         1
	*   ERFCX(ARG)    XNEG .LT. ARG .LT. XMAX   ERFCX(ARG)        2
	*
	* The main computation evaluates near-minimax approximations
	* from "Rational Chebyshev approximations for the error function"
	* by W. J. Cody, Math. Comp., 1969, PP. 631-638.  This
	* transportable program uses rational functions that theoretically
	* approximate  erf(x)  and  erfc(x)  to at least 18 significant
	* decimal digits.  The accuracy achieved depends on the arithmetic
	* system, the compiler, the intrinsic functions, and proper
	* selection of the machine-dependent constants.
	*/

	let RESULT = 0;
	let Y = Math.abs( X );
	let YSQ, XNUM, XDEN;
     
	if (Y <= THRESH) { // Evaluate  erf  for  |X| <= 0.46875
	    YSQ = 0;
	    if ( Y > XSMALL ) {
	        YSQ = Y * Y;
	    }
	    XNUM = ERF_A[4] * YSQ;
	    XDEN = YSQ;
	    for ( let i = 0; i < 3; i++) {
	        XNUM = ( XNUM + ERF_A[i] ) * YSQ;
	        XDEN = ( XDEN + ERF_B[i] ) * YSQ;
	    }
	    RESULT = X * ( XNUM + ERF_A[3] ) / ( XDEN + ERF_B[3] );
	    if ( jint != 0 ) {
	        RESULT = 1.0 - RESULT;
	    }
	    if ( jint == 2 ) {
	        RESULT = Math.exp( YSQ ) * RESULT;
	    }
	    return RESULT;
        
	} else if ( Y <= 4 ) { // Evaluate  erfc  for 0.46875 <= |X| <= 4.0
	    XNUM = ERF_C[8] * Y;
	    XDEN = Y;
	    for ( let i = 0; i < 7; i++) {
	        XNUM = ( XNUM + ERF_C[i] ) * Y;
	        XDEN = ( XDEN + ERF_D[i] ) * Y;
	    }
	    RESULT = ( XNUM + ERF_C[7] ) / ( XDEN + ERF_D[7] );
	    if ( jint != 2 ) {
	        YSQ = Math.round( Y * 16 ) / 16;
	        let del = ( Y - YSQ ) * ( Y + YSQ );
	        RESULT = Math.exp( -YSQ * YSQ ) * Math.exp( -del ) * RESULT;
	    }      

	} else { // Evaluate  erfc  for |X| > 4.0
	    RESULT = 0;
	    if ( Y >= XBIG && ( jint != 2 || Y >= XMAX ) ) {
	        ;
	    } else if ( Y >= XBIG && Y >= XHUGE ) {
	        RESULT = SQRTPI / Y;
	    } else {
	        YSQ = 1.0 / ( Y * Y );
	        XNUM = ERF_P[5] * YSQ;
	        XDEN = YSQ;
	        for ( let i = 0; i < 4; i++ ) {
		        XNUM = ( XNUM + ERF_P[i] ) * YSQ;
	            XDEN = ( XDEN + ERF_Q[i] ) * YSQ;
	        }
	        RESULT = YSQ * ( XNUM + ERF_P[4] ) / ( XDEN + ERF_Q[4] );
	        RESULT = ( SQRTPI - RESULT ) / Y;
	        if ( jint != 2 ) {
	            YSQ = Math.round( Y * 16 ) / 16.0;
	            let del = ( Y - YSQ ) * ( Y + YSQ );
	            RESULT = Math.exp( -YSQ * YSQ ) * Math.exp( -del ) * RESULT;
	        }
	    }
	} 
    // Fix up for negative argument, erf, etc.
	if ( jint == 0 ) {
	    RESULT = 0.5 - RESULT + 0.5;
	    if ( X < 0 ) {
	        RESULT = -RESULT;
	    }
	} else if ( jint == 1 ) {
	    if ( X < 0 ) {
	        RESULT = 2 - RESULT;
	    }
	} else {
	    if ( X < 0 ) {
	        if ( X < XNEG ) {
	            RESULT = XINF;
	        } else {
	            YSQ = Math.round( X * 16 ) / 16;
	            let del = ( X - YSQ ) * ( X + YSQ );
	            Y = Math.exp( YSQ * YSQ ) * Math.exp( del );
	            RESULT = Y + Y - RESULT;
	        }
	    }
	}
	return RESULT;
}

/* 
 * ******************************************************
 * INVERSE COMPLEMENTARY ERROR FUNCTION (ERFCINV)
 * ******************************************************
 * 
 *  (C) Copyright John Maddock 2006.
 *  Use, modification and distribution are subject to the
 *  Boost Software License, Version 1.0. (See accompanying file
 *  LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
*/
// CONSTANTS FOR ERFCINV
const YPLEQ05 = 0.0891314744949340820313;
const PPLEQ05 = [-0.000508781949658280665617,-0.00836874819741736770379,0.0334806625409744615033,-0.0126926147662974029034,-0.0365637971411762664006,0.0219878681111168899165,0.00822687874676915743155,-0.00538772965071242932965];
const QPLEQ05 = [1.0,-0.970005043303290640362,-1.56574558234175846809,1.56221558398423026363,0.662328840472002992063,-0.71228902341542847553,-0.0527396382340099713954,0.0795283687341571680018,-0.00233393759374190016776,0.000886216390456424707504];
const YQGEQ025 = 2.249481201171875;
const PQGEQ025 = [-0.202433508355938759655,0.105264680699391713268,8.37050328343119927838,17.6447298408374015486,-18.8510648058714251895,-44.6382324441786960818,17.445385985570866523,21.1294655448340526258,-3.67192254707729348546];    
const QQGEQ025 = [1.0,6.24264124854247537712,3.9713437953343869095,-28.6608180499800029974,-20.1432634680485188801,48.5609213108739935468,10.8268667355460159008,-22.6436933413139721736,1.72114765761200282724];
const YXL3 = 0.807220458984375;
const PXL3 = [-0.131102781679951906451,-0.163794047193317060787,0.117030156341995252019,0.387079738972604337464,0.337785538912035898924,0.142869534408157156766,0.0290157910005329060432,0.00214558995388805277169,-0.679465575181126350155e-6,0.285225331782217055858e-7,-0.681149956853776992068e-9];
const QXL3 = [1.0,3.46625407242567245975,5.38168345707006855425,4.77846592945843778382,2.59301921623620271374,0.848854343457902036425,0.152264338295331783612,0.01105924229346489121];
const YXL6 = 0.93995571136474609375;
const PXL6 = [-0.0350353787183177984712,-0.00222426529213447927281,0.0185573306514231072324,0.00950804701325919603619,0.00187123492819559223345,0.000157544617424960554631,0.460469890584317994083e-5,-0.230404776911882601748e-9,0.266339227425782031962e-11];  
const QXL6 = [1.0,1.3653349817554063097,0.762059164553623404043,0.220091105764131249824,0.0341589143670947727934,0.00263861676657015992959,0.764675292302794483503e-4];
const YXL18 = 0.98362827301025390625;
const PXL18 = [-0.0167431005076633737133,-0.00112951438745580278863,0.00105628862152492910091,0.000209386317487588078668,0.149624783758342370182e-4,0.449696789927706453732e-6,0.462596163522878599135e-8,-0.281128735628831791805e-13,0.99055709973310326855e-16];
const QXL18 = [1.0,0.591429344886417493481,0.138151865749083321638,0.0160746087093676504695,0.000964011807005165528527,0.275335474764726041141e-4,0.282243172016108031869e-6];
const YXL44 = 0.99714565277099609375;
const PXL44 = [-0.0024978212791898131227,-0.779190719229053954292e-5,0.254723037413027451751e-4,0.162397777342510920873e-5,0.396341011304801168516e-7,0.411632831190944208473e-9,0.145596286718675035587e-11,-0.116765012397184275695e-17];
const QXL44 = [1.0,0.207123112214422517181,0.0169410838120975906478,0.000690538265622684595676,0.145007359818232637924e-4,0.144437756628144157666e-6,0.509761276599778486139e-9];
const YELSE = 0.99941349029541015625;
const PELSE = [-0.000539042911019078575891,-0.28398759004727721098e-6,0.899465114892291446442e-6,0.229345859265920864296e-7,0.225561444863500149219e-9,0.947846627503022684216e-12,0.135880130108924861008e-14,-0.348890393399948882918e-21];
const QELSE = [1.0,0.0845746234001899436914,0.00282092984726264681981,0.468292921940894236786e-4,0.399968812193862100054e-6,0.161809290887904476097e-8,0.231558608310259605225e-11];

function erfcinv( z ) {
    // Begin by testing for domain errors, and other special cases:
	if ( Number.isNaN( z ) || z > 2 || z < 0  ) {
		return Number.NaN;
	} else if ( z === 0 ) {
		return Number.POSITIVE_INFINITY;
	} else if ( z === 2 ) {
		return Number.NEGATIVE_INFINITY;
	} else if ( z === 1 ) {
		return 0;
	}
	// Normalise the input, so it's in the range [0,1], we will
    // negate the result if z is outside that range. This is a simple
    // application of the erfc reflection formula: erfc(-z) = 2 - erfc(z)
    let s, q, p;
	if ( z > 1 ) {
		q = 2 - z;
        p = 1 - q;
		s = -1;
	} else {
        p = 1 - z;
		q = z;
		s = 1;
	}	
	if ( p <= 0.5 ) { 
        // Evaluate inverse erf using the rational approximation:
        //
        // x = p(p+10)(Y+R(p))
        //
        // Where Y is a constant, and R(p) is optimised for a low
        // absolute error compared to |Y|.
        //
        let g = p * ( p + 10 );
		let r = evaluate_polynomial( PPLEQ05, p ) / evaluate_polynomial( QPLEQ05, p );
		return  s * g * ( YPLEQ05 + r );

	} else if ( q >= 0.25 ) {
        // Rational approximation for 0.5 > q >= 0.25
        //
        // x = sqrt(-2*log(q)) / (Y + R(q))
        //
        // Where Y is a constant, and R(q) is optimised for a low
        // absolute error compared to Y.
        //
        let g = Math.sqrt( -2 * Math.log( q ) );
		let xs = q - 0.25;
		let r = evaluate_polynomial( PQGEQ025, xs ) / evaluate_polynomial( QQGEQ025, xs );
		return s * g / ( YQGEQ025 + r );

	} else {
        // For q < 0.25 we have a series of rational approximations all
        // of the general form:
        //
        // let: x = sqrt(-log(q))
        //
        // Then the result is given by:
        //
        // x(Y+R(x-B))
        //
        // where Y is a constant, B is the lowest value of x for which
        // the approximation is valid, and R(x-B) is optimised for a low
        // absolute error compared to Y.ƒ‹
        //
        // Note that almost all code will really go through the firstƒ‹
        // or maybe second approximation. After than we're dealing with very
        // small input values indeed: 80 and 128 bit long double's go all the
        // way down to ~ 1e-5000 so the "tail" is rather long...
        //
	    let x = Math.sqrt( -Math.log( q ) );

	    if ( x < 3 ) {
            let xs = x - 1.125;
            let R = evaluate_polynomial( PXL3, xs ) / evaluate_polynomial( QXL3, xs );
            return s * x * ( YXL3 + R );   

	    } else if ( x < 6 ) {
            let xs = x - 3;
            let R = evaluate_polynomial( PXL6, xs ) / evaluate_polynomial( QXL6, xs );
            return s * x * ( YXL6 + R );   

	    } else if( x < 18 ){
            let xs = x - 6;
            let R = evaluate_polynomial( PXL18, xs ) / evaluate_polynomial( QXL18, xs );
            return s * x * ( YXL18 + R );   

        } else if( x < 44 ){
            let xs = x - 18;
            let R = evaluate_polynomial( PXL44, xs ) / evaluate_polynomial( QXL44, xs );
            return s * x * ( YXL44 + R );   
        
        } else {
            let xs = x - 44;     
            let R = evaluate_polynomial( PELSE, xs ) / evaluate_polynomial( QELSE, xs );
            return s * x * ( YELSE + R );   
        }
    }
}

function evaluate_polynomial( polynomial_coeff, x ){
    let y = 0;
    for ( let i = polynomial_coeff.length-1; i>-1; i-- ){
        y = x * ( polynomial_coeff[i] + y ); 
    }
    return y;
}

/* 
 * ******************************************************
 * INVERSE ERROR FUNCTION (ERFINV)
 * ******************************************************
*/

// CONSTANTS USED IN ERFINV
const LN2 = 6.931471805599453094172321214581e-1;
  
const A0 = 1.1975323115670912564578e0;
const A1 = 4.7072688112383978012285e1;
const A2 = 6.9706266534389598238465e2;
const A3 = 4.8548868893843886794648e3;
const A4 = 1.6235862515167575384252e4;
const A5 = 2.3782041382114385731252e4;
const A6 = 1.1819493347062294404278e4;
const A7 = 8.8709406962545514830200e2;
  
const B0 = 1.0000000000000000000e0;
const B1 = 4.2313330701600911252e1;
const B2 = 6.8718700749205790830e2;
const B3 = 5.3941960214247511077e3;
const B4 = 2.1213794301586595867e4;
const B5 = 3.9307895800092710610e4;
const B6 = 2.8729085735721942674e4;
const B7 = 5.2264952788528545610e3;
  
const C0 = 1.42343711074968357734e0;
const C1 = 4.63033784615654529590e0;
const C2 = 5.76949722146069140550e0;
const C3 = 3.64784832476320460504e0;
const C4 = 1.27045825245236838258e0;
const C5 = 2.41780725177450611770e-1;
const C6 = 2.27238449892691845833e-2;
const C7 = 7.74545014278341407640e-4;
  
const D0 = 1.4142135623730950488016887e0;
const D1 = 2.9036514445419946173133295e0;
const D2 = 2.3707661626024532365971225e0;
const D3 = 9.7547832001787427186894837e-1;
const D4 = 2.0945065210512749128288442e-1;
const D5 = 2.1494160384252876777097297e-2;
const D6 = 7.7441459065157709165577218e-4;
const D7 = 1.4859850019840355905497876e-9;
  
const E0 = 6.65790464350110377720e0;
const E1 = 5.46378491116411436990e0;
const E2 = 1.78482653991729133580e0;
const E3 = 2.96560571828504891230e-1;
const E4 = 2.65321895265761230930e-2;
const E5 = 1.24266094738807843860e-3;
const E6 = 2.71155556874348757815e-5;
const E7 = 2.01033439929228813265e-7;
  
const F0 = 1.414213562373095048801689e0;
const F1 = 8.482908416595164588112026e-1;
const F2 = 1.936480946950659106176712e-1;
const F3 = 2.103693768272068968719679e-2;
const F4 = 1.112800997078859844711555e-3;
const F5 = 2.611088405080593625138020e-5;
const F6 = 2.010321207683943062279931e-7;
const F7 = 2.891024605872965461538222e-15;

function erfinv( z ) {

    if ( Number.isNaN( z ) || z < -1 || z > 1 ) {
        return Number.NaN;
    } else if ( z == 1 ) {
        return Number.POSITIVE_INFINITY;
    } else if ( z == -1 ) {
        return Number.NEGATIVE_INFINITY;
    }
    let r, num, den;    
    let absx = Math.abs( z );
  
    if ( absx <= 0.85 ) {
        r = 0.180625 - 0.25 * z * z;
        num = (((((((A7 * r + A6) * r + A5) * r + A4) * r + A3) * r + A2) * r + A1) * r + A0);
        den = (((((((B7 * r + B6) * r + B5) * r + B4) * r + B3) * r + B2) * r + B1) * r + B0);
        return z * num / den;
    } else {  
        r = Math.sqrt( LN2 - Math.log( 1 - absx ) );
  
        if ( r <= 5 ) {
            r = r - 1.6;
            num = (((((((C7 * r + C6) * r + C5) * r + C4) * r + C3) * r + C2) * r + C1) * r + C0);
            den = (((((((D7 * r + D6) * r + D5) * r + D4) * r + D3) * r + D2) * r + D1) * r + D0);
        } else {
            r = r - 5;
            num = (((((((E7 * r + E6) * r + E5) * r + E4) * r + E3) * r + E2) * r + E1) * r + E0);
            den = (((((((F7 * r + F6) * r + F5) * r + F4) * r + F3) * r + F2) * r + F1) * r + F0);
        }
        return Math.sign( z ) * ( num / den );
    }
}
  
  
function erfinv_refine( z, nr_iter ) {
    const k = 0.8862269254527580136490837416706; // 0.5 * sqrt(pi)
    y = erfinv( z );
    while ( nr_iter-- > 0 ) {
        y -= k * ( erf( y ) - z) / Math.exp( -y * y );
    }
    return y;
}