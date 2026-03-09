import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta

st.set_page_config(page_title="Planejador NHS", page_icon="🏭", layout="wide")

URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

# Padrões de N Natural por Célula
PADROES_N = {
    "UPS - 1": 5, "UPS - 2": 3, "UPS - 3": 3, "UPS - 4": 3,
    "UPS - 6": 4, "UPS - 7": 4, "UPS - 8": 4, "ACS - 01": 2
}

@st.cache_data(ttl=10)
def carregar_base():
    try:
        # Lê a planilha bruta sem cabeçalho para escanear tudo
        df_raw = pd.read_csv(URL_BASE, header=None)
        
        # BUSCA DINÂMICA: Procura a linha que contém "MODELO" em qualquer lugar
        m_row, m_col = -1, -1
        for r in range(min(50, len(df_raw))):
            for c in range(min(15, len(df_raw.columns))):
                val = str(df_raw.iloc[r, c]).strip().upper()
                if "MODELO" in val:
                    m_row, m_col = r, c
                    break
            if m_row != -1: break
        
        if m_row == -1:
            return pd.DataFrame() # Se não achar a palavra MODELO, retorna vazio

        # Extração baseada na posição onde o MODELO foi encontrado
        dados = df_raw.iloc[m_row+1:].copy()
        df_f = pd.DataFrame()
        
        # Modelo está na coluna onde foi achado o título
        df_f['ID'] = dados.iloc[:, m_col].astype(str).str.strip()
        # Unidade Hora está na coluna seguinte (coluna G / 6)
        df_f['UNIDADE_HORA'] = pd.to_numeric(dados.iloc[:, m_col+1], errors='coerce')
        # Descrição está duas colunas depois (coluna H / 7)
        df_f['DESCRICAO'] = dados.iloc[:, m_col+2].astype(str).str.strip()
        # Célula está três colunas depois (coluna I / 8)
        cel_col_idx = m_col + 3
        celula_raw = dados.iloc[:, cel_col_idx].replace(['nan', 'None', '', 'NAN'], None)
        df_f['CELULA'] = celula_raw.ffill().astype(str).str.strip()
        
        # LIMPEZA PESADA
        # Remove linhas que não são modelos reais (títulos repetidos ou lixo)
        df_f = df_f[df_f['ID'].str.len() > 4]
        df_f = df_f[~df_f['ID'].str.contains('MODELO|UNIDADE|DESCRIÇÃO', case=False, na=False)]
        # Garante que só pegue UPS ou ACS
        df_f = df_f[df_f['CELULA'].str.contains('UPS|ACS', case=False, na=False)]
        
        # Texto para o seletor
        df_f['DISPLAY'] = df_f['ID'] + " - " + df_f['DESCRICAO'] + " (" + df_f['UNIDADE_HORA'].astype(str) + " pç/h)"
        
        return df_f.dropna(subset=['UNIDADE_HORA', 'CELULA'])
    except Exception as e:
        st.error(f"Erro na leitura: {e}")
        return pd.DataFrame()

# --- FUNÇÕES DE CÁLCULO (MANTIDAS) ---
def gerar_grade(h_ini, tem_gin):
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
                if tem_gin and inter == "09:30–10:30": m -= 10
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
        p_b, mods = 0, []
        while c_idx < len(df_in):
            t_p, mod_id = df_in.loc[c_idx, 'T_PC'], df_in.loc[c_idx, 'ID']
            if pd.isna(t_p) or t_p <= 0: c_idx += 1; continue
            if acum >= (t_p - 0.01):
                q = min(math.floor(acum / t_p + 0.01), df_in.loc[c_idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_p); df_in.loc[c_idx, 'FALTA'] -= q
                    tot += q; p_b += q
                    mods.append(f"{mod_id} ({int(q)} pçs)")
                if df_in.loc[c_idx, 'FALTA'] <= 0: c_idx += 1
                else: break
            else: break
        res.append({'Horário': hor, 'Modelos': " + ".join(mods) if mods else "-", 'Peças': int(p_b), 'Acumulada': int(tot)})
        if tot >= total_desejado and termino == "Incompleto" and total_desejado > 0:
            termino = (f_dt - timedelta(minutes=acum)).strftime("%H:%M")
    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
try:
    base = carregar_base()
    if not base.empty:
        st.sidebar.title("⚙️ Controle")
        lista_ups = sorted(base['CELULA'].unique().tolist())
        sel_ups = st.sidebar.selectbox("Selecionar Célula", lista_ups)
        
        v_padrao = PADROES_N.get(sel_ups, 3)
        h_ini = st.sidebar.text_input("Início", value="08:00")
        tem_gin = st.sidebar.checkbox("Ginástica Laboral?", value=False)
        n_nat = st.sidebar.number_input("N Natural", value=v_padrao, min_value=1)
        n_dia = st.sidebar.number_input("N do Dia", value=v_padrao, min_value=1)
        fator = n_dia / n_nat

        df_f = base[base['CELULA'] == sel_ups]
        opcoes = sorted(df_f['DISPLAY'].tolist())

        col1, col2 = st.columns([0.8, 0.2])
        with col1: st.header(f"📋 Programação: {sel_ups}")
        with col2: 
            if st.button("🗑️ Limpar Tudo"): 
                st.session_state["reset_key"] = st.session_state.get("reset_key", 0) + 1
                st.rerun()

        key_ed = f"ed_{sel_ups}_{st.session_state.get('reset_key', 0)}"
        df_editor = st.data_editor(
            pd.DataFrame(columns=["Equipamento", "Qtd"]),
            num_rows="dynamic", use_container_width=True,
            column_config={
                "Equipamento": st.column_config.SelectboxColumn("Equipamento", options=opcoes, required=True),
                "Qtd": st.column_config.NumberColumn("Qtd", min_value=0, default=0)
            }, key=key_ed
        )

        if st.button("🚀 Gerar Planejamento"):
            if not df_editor.empty:
                r = calcular(df_editor, base, h_ini, fator, tem_gin)
                st.divider()
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total", f"{int(r['tot'])} pçs")
                m2.metric("Término", r['termino'])
                m3.metric("Fator", f"{fator:.2%}")
                m4.metric("Ginástica", "SIM" if tem_gin else "NÃO")
                st.table(r['df'])
            else:
                st.warning("Adicione modelos na tabela.")
    else:
        st.error("⚠️ Estrutura não detectada. Verifique se a palavra 'MODELO' está na coluna F.")

except Exception as e:
    st.error(f"Erro Crítico: {e}")
