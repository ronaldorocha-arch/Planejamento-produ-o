import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Planejador NHS", page_icon="🏭", layout="wide")

# Link da sua planilha do Google (Base de Dados)
URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

# 2. PADRÕES DE EFICIÊNCIA (N NATURAL)
PADROES_N = {
    "UPS - 1": 5, "UPS - 2": 3, "UPS - 3": 3, "UPS - 4": 3,
    "UPS - 6": 4, "UPS - 7": 4, "UPS - 8": 4, "ACS - 01": 2
}

# 3. FUNÇÃO PARA CARREGAR E ESCANEAR A PLANILHA
@st.cache_data(ttl=10)
def carregar_base():
    try:
        # Lê a planilha bruta para escanear a estrutura
        df_raw = pd.read_csv(URL_BASE, header=None)
        
        # BUSCA AUTOMÁTICA: Procura a palavra "MODELO" em qualquer célula
        m_row, m_col = -1, -1
        for r in range(min(60, len(df_raw))): 
            for c in range(min(20, len(df_raw.columns))):
                val = str(df_raw.iloc[r, c]).strip().upper()
                if val == "MODELO":
                    m_row, m_col = r, c
                    break
            if m_row != -1: break
        
        if m_row == -1:
            return pd.DataFrame() # Retorna vazio se não achar o cabeçalho

        # Extrai os dados a partir da linha onde achou "MODELO"
        dados = df_raw.iloc[m_row+1:].copy()
        df_f = pd.DataFrame()
        
        # Mapeia as colunas baseadas na posição do título "MODELO"
        df_f['ID'] = dados.iloc[:, m_col].astype(str).str.strip()
        df_f['UNIDADE_HORA'] = pd.to_numeric(dados.iloc[:, m_col+1], errors='coerce')
        df_f['DESCRICAO'] = dados.iloc[:, m_col+2].astype(str).str.strip()
        
        # Célula/UPS (Geralmente 3 colunas à direita do Modelo)
        cel_col_idx = m_col + 3
        celula_raw = dados.iloc[:, cel_col_idx].replace(['nan', 'None', '', 'NAN'], None)
        df_f['CELULA'] = celula_raw.ffill().astype(str).str.strip()
        
        # Limpeza de lixo (remove títulos repetidos e linhas curtas)
        df_f = df_f[df_f['ID'].str.len() > 4]
        df_f = df_f[~df_f['ID'].str.contains('MODELO|UNIDADE|DESCRIÇÃO', case=False, na=False)]
        
        # Filtra para garantir que a célula seja uma UPS ou ACS válida
        df_f = df_f[df_f['CELULA'].str.contains('UPS|ACS', case=False, na=False)]
        
        # Texto formatado para o seletor (Dropdown)
        df_f['DISPLAY'] = df_f['ID'] + " - " + df_f['DESCRICAO'] + " (" + df_f['UNIDADE_HORA'].astype(str) + " pç/h)"
        
        return df_f.dropna(subset=['UNIDADE_HORA', 'CELULA'])
    except Exception as e:
        st.error(f"Erro na leitura da planilha: {e}")
        return pd.DataFrame()

# 4. FUNÇÃO PARA GERAR A GRADE HORÁRIA
def gerar_grade(h_ini, tem_ginastica):
    fmt = "%H:%M"
    # Marcos de tempo da fábrica
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    mins_pad = [50, 60, 60, 0, 60, 60, 50, 60, 60] # 0 min = Almoço
    
    try: 
        ini = datetime.strptime(h_ini, fmt)
    except: 
        ini = datetime.strptime("07:12", fmt)
    
    grade, atual = [], ini
    for i, m_s in enumerate(marcos):
        m_dt = datetime.strptime(m_s, fmt)
        if m_dt > atual:
            dur = (m_dt - atual).seconds // 60
            # Pausas de café fixas (9h e 15h) de 10 minutos
            if (atual <= datetime.strptime("09:00", fmt) < m_dt) or \
               (atual <= datetime.strptime("15:00", fmt) < m_dt):
                dur -= 10
            
            grade.append({'Horário': f"{atual.strftime(fmt)}–{m_s}", 'Minutos': max(0, dur), 'Fim_dt': m_dt})
            
            # Preenche o restante dos blocos padrão
            for j in range(i, len(marcos) - 1):
                inter = f"{marcos[j]}–{marcos[j+1]}"
                m = mins_pad[j]
                if tem_ginastica and inter == "09:30–10:30": 
                    m -= 10
                grade.append({'Horário': inter, 'Minutos': m, 'Fim_dt': datetime.strptime(marcos[j+1], fmt)})
            break
    return pd.DataFrame(grade)

# 5. FUNÇÃO DE CÁLCULO DE PRODUÇÃO
def calcular(df_in, df_ba, h_ini, fat, tem_gin):
    slots = gerar_grade(h_ini, tem_gin)
    # Busca dados na base global
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
        p_b, mods_bloco = 0, []
        
        while c_idx < len(df_in):
            t_p, mod_id = df_in.loc[c_idx, 'T_PC'], df_in.loc[c_idx, 'ID']
            if pd.isna(t_p) or t_p <= 0: 
                c_idx += 1
                continue
            
            if acum >= (t_p - 0.01):
                q = min(math.floor(acum / t_p + 0.01), df_in.loc[c_idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_p)
                    df_in.loc[c_idx, 'FALTA'] -= q
                    tot += q
                    p_b += q
                    mods_bloco.append(f"{mod_id} ({int(q)} pçs)")
                
                if df_in.loc[c_idx, 'FALTA'] <= 0: c_idx += 1
                else: break
            else: break
            
        res.append({
            'Horário': hor, 
            'Modelos': " + ".join(mods_bloco) if mods_bloco else "-", 
            'Peças': int(p_b), 
            'Acumulada': int(tot)
        })
        
        if tot >= total_desejado and termino == "Incompleto" and total_desejado > 0:
            termino = (f_dt - timedelta(minutes=acum)).strftime("%H:%M")

    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# 6. INTERFACE STREAMLIT
try:
    base = carregar_base()
    if not base.empty:
        st.sidebar.title("⚙️ Controle")
        
        # Seleção de Célula (Filtro)
        lista_ups = sorted(base['CELULA'].unique().tolist())
        sel_ups = st.sidebar.selectbox("Selecionar Célula", lista_ups)
        
        # Padrões Automáticos de N Natural
        v_padrao = PADROES_N.get(sel_ups, 3)
        h_ini = st.sidebar.text_input("Início", value="08:00")
        tem_gin = st.sidebar.checkbox("Ginástica Laboral?", value=False)
        
        n_nat = st.sidebar.number_input("N Natural (Padrão)", value=v_padrao, min_value=1, step=1)
        n_dia = st.sidebar.number_input("N do Dia (Real)", value=v_padrao, min_value=1, step=1)
        fator = n_dia / n_nat

        # Filtra as opções para a tabela baseada na UPS
        df_f = base[base['CELULA'] == sel_ups]
        opcoes = sorted(df_f['DISPLAY'].tolist())

        col1, col2 = st.columns([0.8, 0.2])
        with col1: 
            st.header(f"📋 Programação: {sel_ups}")
        with col2: 
            if st.button("🗑️ Limpar Tudo"): 
                st.session_state["reset_key"] = st.session_state.get("reset_key", 0) + 1
                st.rerun()

        # Editor de Dados (Tabela de entrada)
        key_ed = f"ed_{sel_ups}_{st.session_state.get('reset_key', 0)}"
        df_editor = st.data_editor(
            pd.DataFrame(columns=["Equipamento", "Qtd"]),
            num_rows="dynamic", use_container_width=True,
            column_config={
                "Equipamento": st.column_config.SelectboxColumn("Equipamento", options=opcoes, required=True),
                "Qtd": st.column_config.NumberColumn("Quantidade", min_value=0, default=0)
            }, key=key_ed
        )

        if st.button("🚀 Gerar Planejamento"):
            if not df_editor.empty:
                r = calcular(df_editor, base, h_ini, fator, tem_gin)
                st.divider()
                # Métricas de Resumo
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total", f"{int(r['tot'])} pçs")
                m2.metric("Término Estimado", r['termino'])
                m3.metric("Fator Eficiência", f"{fator:.2%}")
                m4.metric("Ginástica", "SIM" if tem_gin else "NÃO")
                
                # Cronograma Final
                st.subheader("🗓️ Cronograma Detalhado")
                st.table(r['df'])
            else:
                st.warning("Adicione modelos na tabela para calcular.")
    else:
        st.error("⚠️ Estrutura da Planilha não detectada. Verifique se a palavra 'MODELO' está na Coluna F da primeira aba.")

except Exception as e:
    st.error(f"Erro Crítico: {e}")
