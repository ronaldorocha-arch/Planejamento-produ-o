import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta

# Configuração da página
st.set_page_config(page_title="Planejador NHS", page_icon="🏭", layout="wide")

# Link da planilha do Google
URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

@st.cache_data(ttl=30)
def carregar_base():
    df_raw = pd.read_csv(URL_BASE, header=None)
    m_row, m_col, u_col, c_col, d_col = -1, -1, -1, -1, -1
    for r in range(min(20, len(df_raw))):
        for c in range(min(20, len(df_raw.columns))):
            val = str(df_raw.iloc[r, c]).strip().upper()
            if val == "MODELO": m_row, m_col = r, c
            elif "UNIDADE" in val and "HORA" in val: u_col = c
            elif "DESCRIÇÃO" in val: d_col = c
            elif val == "CELULA": c_col = c
    if m_row == -1: return pd.DataFrame()
    if c_col == -1: c_col = df_raw.columns[-1]
    if d_col == -1: d_col = m_col + 2
    dados = df_raw.iloc[m_row+1:].copy()
    df_f = pd.DataFrame()
    df_f['ID'] = dados.iloc[:, m_col].astype(str).str.strip()
    df_f['UNIDADE_HORA'] = pd.to_numeric(dados.iloc[:, u_col], errors='coerce')
    df_f['DESCRICAO'] = dados.iloc[:, d_col].astype(str).str.strip()
    df_f['CELULA'] = dados.iloc[:, c_col].fillna(method='ffill').astype(str).str.strip()
    df_f['DISPLAY'] = df_f['ID'] + " - " + df_f['DESCRICAO'] + " (" + df_f['UNIDADE_HORA'].astype(str) + " pç/h)"
    return df_f[df_f['ID'] != 'nan'].dropna(subset=['UNIDADE_HORA'])

def gerar_grade(h_ini, tem_ginastica):
    fmt = "%H:%M"
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    mins_pad = [50, 60, 60, 0, 60, 60, 50, 60, 60]
    try: ini = datetime.strptime(h_ini, fmt)
    except: ini = datetime.strptime("07:12", fmt)
    grade, atual = [], ini
    for i, m_s in enumerate(marcos):
        m_dt = datetime.strptime(m_s, fmt)
        if m_dt > atual:
            dur = (m_dt - atual).seconds // 60
            if (atual <= datetime.strptime("09:00", fmt) < m_dt) or (atual <= datetime.strptime("15:00", fmt) < m_dt):
                dur -= 10
            grade.append({'Horário': f"{atual.strftime(fmt)}–{m_s}", 'Minutos': max(0, dur), 'Fim_dt': m_dt})
            for j in range(i, len(marcos) - 1):
                inter = f"{marcos[j]}–{marcos[j+1]}"
                m = mins_pad[j]
                if tem_ginastica and inter == "09:30–10:30": m -= 10
                grade.append({'Horário': inter, 'Minutos': m, 'Fim_dt': datetime.strptime(marcos[j+1], fmt)})
            break
    return pd.DataFrame(grade)

def calcular(df_in, df_ba, h_ini, fat, tem_gin):
    slots = gerar_grade(h_ini, tem_gin)
    df_in = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA']], left_on='Equipamento', right_on='DISPLAY', how='left')
    df_in['CAD_R'] = df_in['UNIDADE_HORA'] * fat
    df_in['T_PC'] = 60 / df_in['CAD_R']
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'], errors='coerce').fillna(0)
    total_desejado = df_in['FALTA'].sum()
    res, acum, c_idx, tot = [], 0.0, 0, 0
    termino = "Incompleto"

    for _, s in slots.iterrows():
        hor, t_b, f_dt = s['Horário'], s['Minutos'], s['Fim_dt']
        if t_b == 0:
            res.append({'Horário': hor, 'Modelos': 'ALMOÇO', 'Peças': 0, 'Acumulada': tot})
            continue
        
        acum += t_b
        p_b = 0
        modelos_no_bloco = []

        while c_idx < len(df_in):
            t_p = df_in.loc[c_idx, 'T_PC']
            mod_id = df_in.loc[c_idx, 'ID']
            if pd.isna(t_p) or t_p <= 0: c_idx += 1; continue
            
            if acum >= (t_p - 0.01):
                q = min(math.floor(acum / t_p + 0.01), df_in.loc[c_idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_p)
                    df_in.loc[c_idx, 'FALTA'] -= q
                    tot += q; p_b += q
                    # Registra qual modelo e quantas peças dele saíram neste bloco
                    modelos_no_bloco.append(f"{mod_id} ({int(q)} pçs)")
                
                if df_in.loc[c_idx, 'FALTA'] <= 0: c_idx += 1
                else: break
            else: break
        
        res.append({
            'Horário': hor, 
            'Modelos': " + ".join(modelos_no_bloco) if modelos_no_bloco else "-",
            'Peças': int(p_b), 
            'Acumulada': int(tot)
        })
        
        if tot >= total_desejado and termino == "Incompleto" and total_desejado > 0:
            termino = (f_dt - timedelta(minutes=acum)).strftime("%H:%M")

    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- Interface ---
try:
    base = carregar_base()
    if not base.empty:
        st.sidebar.title("⚙️ Controle")
        sel_ups = st.sidebar.selectbox("Filtrar lista", ["TODAS"] + sorted(base['CELULA'].unique().tolist()))
        h_ini = st.sidebar.text_input("Início", value="07:12")
        tem_gin = st.sidebar.checkbox("Ginástica Laboral?", value=False)
        n_nat = st.sidebar.number_input("N Natural", value=3, min_value=1)
        n_dia = st.sidebar.number_input("N do Dia", value=3, min_value=1)
        fator = n_dia / n_nat

        col1, col2 = st.columns([0.8, 0.2])
        with col1: st.header("📋 Programação de Produção")
        with col2: 
            if st.button("🗑️ Limpar"): 
                st.cache_data.clear(); st.rerun()

        df_editor = st.data_editor(
            pd.DataFrame(columns=["Equipamento", "Qtd"]),
            num_rows="dynamic", use_container_width=True,
            column_config={
                "Equipamento": st.column_config.SelectboxColumn("Equipamento", options=base['DISPLAY'].tolist(), required=True),
                "Qtd": st.column_config.NumberColumn("Qtd", min_value=0, default=0)
            }, key="editor_vfinal"
        )

        if st.button("🚀 Gerar Planejamento"):
            if not df_editor.empty:
                r = calcular(df_editor, base, h_ini, fator, tem_gin)
                st.divider()
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total", f"{int(r['tot'])} pçs")
                m2.metric("Término Estimado", r['termino'])
                m3.metric("Eficiência", f"{fator:.2%}")
                m4.metric("Ginástica", "SIM" if tem_gin else "NÃO")
                
                # Tabela detalhada agora com a coluna "Modelos"
                st.subheader("🗓️ Cronograma por Modelo")
                st.table(r['df'])
except Exception as e:
    st.error(f"Erro: {e}")
