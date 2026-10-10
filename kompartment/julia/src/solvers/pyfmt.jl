# Numbers in messages as Python writes them (`f'{x}'` of a float is its
# repr): the shortest digits that read back as the same double -- Julia's
# own shortest digits, the same string of digits -- laid out as Python lays
# them out: fixed between 1e-4 and 1e16, '1e-05' / '1.5e+16' outside.

function _pyrepr(x::Float64)::String
    isnan(x) && return "nan"
    isinf(x) && return x > 0 ? "inf" : "-inf"
    x == 0 && return signbit(x) ? "-0.0" : "0.0"
    s = string(abs(x))
    ex = 0
    mant = s
    epos = findfirst(==('e'), s)
    if epos !== nothing
        mant = s[1:epos-1]
        ex = parse(Int, s[epos+1:end])
    end
    dot = findfirst(==('.'), mant)
    ip, fp = dot === nothing ? (mant, "") : (mant[1:dot-1], mant[dot+1:end])
    digits = ip * fp
    decpt = length(ip) + ex
    i = 1
    while i < length(digits) && digits[i] == '0'
        i += 1
        decpt -= 1
    end
    digits = rstrip(digits[i:end], '0')
    nd = length(digits)
    body = if decpt <= -4 || decpt > 16
        e = decpt - 1
        m = nd == 1 ? String(digits) : string(digits[1], '.', digits[2:end])
        string(m, 'e', e < 0 ? '-' : '+', lpad(string(abs(e)), 2, '0'))
    elseif decpt <= 0
        string("0.", "0"^(-decpt), digits)
    elseif decpt >= nd
        string(digits, "0"^(decpt - nd), ".0")
    else
        string(digits[1:decpt], '.', digits[decpt+1:end])
    end
    return x < 0 ? "-" * body : body
end
