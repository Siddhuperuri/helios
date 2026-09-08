"""Consumer-facing estimation domain.

The packages beneath ``app/features``, ``app/models`` and ``app/evaluation`` answer a
physicist's question: *what is the irradiance, and what AC power does a declared array
produce from it?* They answer it well, and nothing here replaces them.

This package answers the question an ordinary person actually asks — *how much solar can
I generate, what will it save me, and should I believe the number?* — by composing those
primitives with the domain they lack: electricity demand, space, cost, tariffs, storage
and confidence.

Three rules hold throughout:

1. **Every number traces to an assumption.** Nothing is a bare constant buried in a
   formula. Defaults live in :mod:`app.estimate.assumptions` with a stated source and are
   returned to the caller alongside the result, so the assumptions panel (§28) and the
   data-source panel (§29) are rendered from data rather than retyped in the UI.
2. **Absent input is never invented.** Where a calculation needs something the user did
   not supply, the module either derives it from a stated default or declines to produce
   the figure. A declined figure is represented explicitly, not as a zero.
3. **The fast path does not train.** A first estimate runs the published physical chain
   over cached historical weather. Machine learning enters only where it measurably helps
   and only when the user asks for the deeper analysis.
"""
