"""Synchronize report filters before constructing Streamlit widgets."""
KEYS=('report_companies','report_periods','report_single_period','report_kinds')

def context(state,analysis):
    token=(analysis.get('id'),analysis.get('name'),tuple(sorted({d['cnpj'] for d in analysis['docs']})))
    if state.get('_report_context')!=token:
        for key in KEYS:
            state.pop(key,None);state.pop('_options_'+key,None)
        state.pop('excel',None);state.pop('excel_signature',None)
        state['_report_context']=token

def multiselect(state,key,options):
    options=list(options);previous=state.get('_options_'+key)
    if key not in state:
        state[key]=options
    elif previous!=options:
        selected=list(state[key])
        kept=[x for x in selected if x in options]
        # Follow an all-selected scope as it changes, without undoing deliberate clearing.
        if selected==previous or previous==[]:
            state[key]=options
        elif kept:
            state[key]=kept
        elif selected:
            state[key]=options
        else:
            state[key]=[]
    state['_options_'+key]=options

def single(state,key,options):
    options=list(options)
    if state.get(key) not in options:state[key]=options[-1] if options else None
    state['_options_'+key]=options
