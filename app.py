import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta

st.set_page_config(page_title="Planejador NHS", page_icon="🏭", layout="wide")

# Link da sua planilha do Google
URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

# Padrões de N Natural por Célula
PADROES_N = {
    "UPS - 1": 5,
    "UPS - 2": 3,
    "UPS - 3": 3,
    "UPS - 4": 3,
    "UPS - 6": 4,
    "UPS - 7": 4,
    "UPS - 8": 4,
    "ACS - 01": 2
}

@st.cache_data(ttl=10) # Reduzi para 10 segundos para atualizar mais rápido se você mudar a planilha
def carregar_base():
    try:
        df_raw = pd.read_csv(URL_BASE, header=None)
        m_row, m_col, u_col, c_col, d_col = -1, -1, -1, -1, -1
        
        # Localiza os cabeçalhos
        for r in range(min(25, len(df_raw))):
            for c in range(min(20, len(df_raw.columns))):
                val = str(df_raw.iloc[r, c]).strip().upper()
                if val == "MODELO": m_row, m_col = r, c
                elif "UNIDADE" in val and "HORA" in val: u_col = c
                elif "DESCRIÇÃO" in val or "DESCRICAO" in val: d_col = c
                elif "CELULA" in val or "CÉLULA" in val: c_col = c
        
        if m_row == -1: return pd.DataFrame()
        
        # Extração e limpeza
        dados = df_raw.iloc[m_row+1:].copy()
        df_f = pd.DataFrame()
        df_f['ID'] = dados.iloc[:, m_col].astype(str).str.strip()
        df_f['UNIDADE_HORA'] = pd.to_numeric(dados.iloc[:, u_col], errors='coerce')
        
        # Pega descrição (coluna H ou busca por nome)
        idx_desc = d_col if d_col != -1 else m_col + 2
        df_f['DESCRICAO'] = dados.iloc[:, idx_desc].astype(str).str.strip()
        
        # Pega Célula e preenche para baixo (ffill)
        idx_cel = c_col if c_col != -1 else df_raw.columns[-1]
        df_f['CELULA'] = dados.iloc[:, idx_cel].replace(['nan', 'None', ''], None).ffill().astype(str).str.strip()
        
        # Filtro Anti-Sujeira: remove linhas onde o modelo é vazio ou "nan"
        df_f = df_f[df_f['ID'].str.lower() != 'nan']
        df_f = df_f[df_f['ID'] != '']
        
        # Cria o nome que aparece no seletor
        df_f['DISPLAY'] = df_f['ID'] + " - " + df_f['DESCRICAO'] + " (" + df_f['UNIDADE_HORA'].astype(str) + " pç/h)"
        
        return df_f.dropna(subset=['UNIDADE_HORA'])
    except Exception as e:
        st.error(f"Erro ao ler planilha: {e}")
        return pd.DataFrame()

def gerar_grade(h_ini, tem_ginastica):
    fmt = "%H:%M"
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    mins_pad = [50, 60, 60, 0, 60, 60, 50, 60, 60] # 0 é o almoço
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
        p_b, modelos_no_bloco = 0, []
        while c_idx < len(df_in):
            t_p, mod_id = df_in.loc[c_idx, 'T_PC'], df_in.loc[c_idx, 'ID']
            if pd.isna(t_p) or t_p <= 0: c_idx += 1; continue
            if acum >= (t_p - 0.01):
                q = min(math.floor(acum / t_p + 0.01), df_in.loc[c_idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_p); df_in.loc[c_idx, 'FALTA'] -= q
                    tot += q; p_b += q
                    modelos_no_bloco.append(f"{mod_id} ({int(q)} pçs)")
                if df_in.loc[c_idx, 'FALTA'] <= 0: c_idx += 1
                else: break
            else: break
        res.append({'Horário': hor, 'Modelos': " + ".join(modelos_no_bloco) if modelos_no_bloco else "-", 'Peças': int(p_b), 'Acumulada': int(tot)})
        if tot >= total_desejado and termino == "Incompleto" and total_desejado > 0:
            termino = (f_dt - timedelta(minutes=acum)).strftime("%H:%M")
    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
try:
    base = carregar_base()
    if not base.empty:
        st.sidebar.title("⚙️ Controle")
        
        # Filtro de UPS
        lista_ups = sorted([u for u in base['CELULA'].unique() if str(u).lower() != 'nan'])
        sel_ups = st.sidebar.selectbox("Selecionar Célula (UPS)", lista_ups)
        
        # Padrões automáticos de N
        valor_padrao_n = PADROES_N.get(sel_ups, 3)
        h_ini = st.sidebar.text_input("Início da Produção", value="08:00")
        tem_gin = st.sidebar.checkbox("Haverá Ginástica Laboral?", value=False)
        
        n_nat = st.sidebar.number_input("N Natural (Padrão)", value=valor_padrao_n, min_value=1, step=1)
        n_dia = st.sidebar.number_input("N do Dia (Real)", value=valor_padrao_n, min_value=1, step=1)
        fator = n_dia / n_nat

        df_f = base[base['CELULA'] == sel_ups]
        opcoes_filtradas = sorted(df_f['DISPLAY'].tolist())

        col1, col2 = st.columns([0.8, 0.2])
        with col1: st.header(f"📋 Programação: {sel_ups}")
        with col2: 
            if st.button("🗑️ Limpar Tudo"): 
                st.session_state["reset_key"] = st.session_state.get("reset_key", 0) + 1
                st.rerun()

        # Chave dinâmica para limpar a tabela de verdade
        chave_editor = f"editor_{sel_ups}_{st.session_state.get('reset_key', 0)}"

        df_editor = st.data_editor(
            pd.DataFrame(columns=["Equipamento", "Qtd"]),
            num_rows="dynamic", use_container_width=True,
            column_config={
                "Equipamento": st.column_config.SelectboxColumn("Equipamento", options=opcoes_filtradas, required=True),
                "Qtd": st.column_config.NumberColumn("Qtd", min_value=0, default=0)
            }, key=chave_editor
        )

        if st.button("🚀 Gerar Planejamento"):
            if not df_editor.empty:
                r = calcular(df_editor, base, h_ini, fator, tem_gin)
                st.divider()
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Planejado", f"{int(r['tot'])} pçs")
                m2.metric("Término Estimado", r['termino'])
                m3.metric("Fator Eficiência", f"{fator:.2%}")
                m4.metric("Ginástica", "SIM" if tem_gin else "NÃO")
                
                st.subheader("🗓️ Cronograma por Modelo")
                st.table(r['df'])
            else:
                st.warning("Adicione equipamentos na tabela acima clicando no (+)")
    else:
        st.error("Planilha vazia ou não encontrada. Verifique os títulos MODELO e CELULA.")

except Exception as e:
    st.error(f"Erro inesperado: {e}")
