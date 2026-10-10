# What a part of the engine not yet carried across raises.

struct NotSupported <: Exception
    message::String
end
Base.showerror(io::IO, e::NotSupported) = print(io, e.message)
