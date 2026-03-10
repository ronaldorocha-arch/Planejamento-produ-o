import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta

st.set_page_config(page_title="Planejador NHS", page_icon="🏭", layout="wide")

URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

# --- CONFIGURAÇÃO DE HORÁRIOS REAIS ---
REGRAS_HORARIOS = {
    "UPS - 1": {"cafe_m": "09:20", "almoco": "11:30", "cafe_t": "15:20", "n_nat": 5},
    "UPS - 2": {"cafe_m": "09:00", "almoco": "11:30", "cafe_t": "15:00", "n_nat": 3},
    "UPS - 3": {"cafe_m": "09:10", "almoco": "11:50", "cafe_t": "15:10", "n_nat": 3},
    "UPS - 4": {"cafe_m": "09:20", "almoco": "11:45", "cafe_t": "15:10", "n_nat": 3},
    "UPS - 6": {"cafe_m": "09:30", "almoco": "11:45", "cafe_t": "15:30", "n_nat": 4},
    "UPS - 7": {"cafe_m": "09:30", "almoco": "11:45", "cafe_t": "15:40", "n_nat": 4},
    "UPS - 8": {"cafe_m": "09:40", "almoco": "11:45", "cafe_t": "15:40", "n_nat": 4},
    "ACS - 01": {"cafe_m": "09:50", "almoco": "11:45", "cafe_t": "15:50", "n_nat": 2},
}

@st.cache_data(ttl=5)
def carregar_base():
    try:
        df_raw = pd.read_csv(URL_BASE, header=None).astype(str)
        m_row = -1
        for r in range(min(300, len(df_raw))):
            val = str(df_raw.iloc[r, 6]).strip().upper()
            if val == "MODELO":
                m_row = r
                break
        if m_row == -1: return pd.DataFrame()
        dados = df_raw.iloc[m_row+1:m_row+3000].copy()
        lista_final, celula_atual = [], "Indefinida"
        for i in range(len(dados)):
            modelo = str(dados.iloc[i, 6]).strip()
            unidade = pd.to_numeric(dados.iloc[i, 7], errors='coerce')
            descricao = str(dados.iloc[i, 8]).strip()
            cel_na_linha = str(dados.iloc[i, 9]).strip().upper()
            if any(x in cel_na_linha for x in ["UPS", "ACS", "ACE"]):
                celula_atual = str(dados.iloc[i, 9]).strip()
            if modelo != 'nan' and len(modelo) > 3 and not pd.isna(unidade):
                lista_final.append({
                    'ID': modelo, 'UNIDADE_HORA': unidade, 'DESCRICAO': descricao,
                    'CELULA': celula_atual, 'DISPLAY': f"{modelo} - {descricao} ({unidade} pç/h)"
                })
        return pd.DataFrame(lista_final)
    except Exception as e:
        st.error(f"Erro na leitura: {e}"); return pd.DataFrame()

def gerar_grade_fixa(h_ini_input, regras, tem_gin):
    def para_min(h_str):
        h, m = map(int, h_str.split(':'))
        return h * 60 + m

    m_cafe_m = para_min(regras['cafe_m'])
    m_almoco_ini = para_min(regras['almoco'])
    m_almoco_fim = m_almoco_ini + 60
    m_cafe_t = para_min(regras['cafe_t'])
    m_gin = para_min("09:30")

    # Grade baseada no horário de início fornecido pelo usuário e depois segue os marcos
    marcos_estaticos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    
    # Criar a lista de pontos começando pelo input do usuário
    pontos_horario = [h_ini_input] + [m for m in marcos_estaticos if para_min(m) > para_min(h_ini_input)]
    
    grade = []
    for i in range(len(pontos_horario)-1):
        p_ini = para_min(pontos_horario[i])
        p_fim = para_min(pontos_horario[i+1])
        
        minutos_uteis = 0
        for m in range(p_ini, p_fim):
            is_cafe_m = (m_cafe_m <= m < m_cafe_m + 10)
            is_almoco = (m_almoco_ini <= m < m_almoco_fim)
            is_cafe_t = (m_cafe_t <= m < m_cafe_t + 10)
            is_ginast = (m_gin <= m < m_gin + 10) if tem_gin else False
            if not (is_cafe_m or is_almoco or is_cafe_t or is_ginast):
                minutos_uteis += 1
        
        grade.append({
            'Horário': f"{pontos_horario[i]} – {pontos_horario[i+1]}",
            'Minutos': minutos_uteis
        })
    return pd.DataFrame(grade)

def calcular(df_in, df_ba, h_ini, fat, tem_gin, regras):
    slots = gerar_grade_fixa(h_ini, regras, tem_gin)
    df_in = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA']], left_on='Equipamento', right_on='DISPLAY', how='left')
    df_in['CAD_R'] = df_in['UNIDADE_HORA'] * fat
    df_in['T_PC'] = 60 / df_in['CAD_R']
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'], errors='coerce').fillna(0)
    
    total_desejado, res, acum, c_idx, tot = df_in['FALTA'].sum(), [], 0.0, 0, 0
    termino = "Não finalizado"
    
    for _, s in slots.iterrows():
        acum += s['Minutos']
        p_b, mods = 0, []
        while c_idx < len(df_in):
            t_p = df_in.loc[c_idx, 'T_PC']
            if pd.isna(t_p) or t_p <= 0: c_idx += 1; continue
            
            if acum >= (t_p - 0.001):
                q = min(math.floor(acum / t_p + 0.001), df_in.loc[c_idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_p)
                    df_in.loc[c_idx, 'FALTA'] -= q
                    tot += q; p_b += q
                    mods.append(f"{df_in.loc[c_idx, 'ID']} ({int(q)} pçs)")
                if df_in.loc[c_idx, 'FALTA'] <= 0: c_idx += 1
                else: break
            else: break
            
        res.append({'Horário': s['Horário'], 'Modelos': " + ".join(mods) if mods else "-", 'Peças': int(p_b), 'Acumulada': int(tot)})
        
        if tot >= total_desejado and termino == "Não finalizado" and total_desejado > 0:
            minutos_usados = s['Minutos'] - acum
            h_str, m_str = s['Horário'].split(' – ')[0].split(':')
            dt_base = datetime.strptime(f"{h_str}:{m_str}", "%H:%M") + timedelta(minutes=minutos_usados)
            termino = dt_base.strftime("%H:%M")

    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
try:
    base = carregar_base()
    if not base.empty:
        st.sidebar.title("⚙️ Controle")
        lista_ups = sorted(base['CELULA'].unique().tolist())
        sel_ups = st.sidebar.selectbox("Selecionar Célula", lista_ups)
        regra_atual = next((v for k, v in REGRAS_HORARIOS.items() if k in sel_ups), REGRAS_HORARIOS["UPS - 1"])
        
        # CAMPO DE VOLTA: Agora você pode editar se quiser, mas inicia em 07:45
        h_ini = st.sidebar.text_input("Início da Produção", value="07:45")
        
        tem_gin = st.sidebar.checkbox("Haverá Ginástica Laboral?", value=False)
        n_nat = st.sidebar.number_input("N Natural", value=regra_atual['n_nat'], min_value=1)
        n_dia = st.sidebar.number_input("N do Dia", value=regra_atual['n_nat'], min_value=1)
        fator = n_dia / n_nat

        df_f = base[base['CELULA'] == sel_ups]
        opcoes = sorted(df_f['DISPLAY'].tolist())
        col1, col2 = st.columns([0.8, 0.2])
        with col1: st.header(f"📋 Programação: {sel_ups}")
        with col2: 
            if st.button("🗑️ Limpar Tudo"): 
                st.session_state["reset_key"] = st.session_state.get("reset_key", 0) + 1
                st.rerun()

        df_editor = st.data_editor(pd.DataFrame(columns=["Equipamento", "Qtd"]), num_rows="dynamic", use_container_width=True,
            column_config={"Equipamento": st.column_config.SelectboxColumn("Equipamento", options=opcoes, required=True), "Qtd": st.column_config.NumberColumn("Qtd", min_value=0, default=0)}, 
            key=f"ed_{sel_ups}_{st.session_state.get('reset_key', 0)}")

        if st.button("🚀 Gerar Planejamento"):
            if not df_editor.empty:
                r = calcular(df_editor, base, h_ini, fator, tem_gin, regra_atual)
                st.divider()
                
                # --- MÉTRICAS NO TOPO ---
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Planejado", f"{int(r['tot'])} pçs")
                c2.metric("Término Estimado", r['termino'])
                c3.metric("Eficiência", f"{fator:.2%}")
                
                c4, c5, c6 = st.columns(3)
                c4.metric("☕ Café Manhã", regra_atual['cafe_m'])
                c5.metric("🍱 Almoço", regra_atual['almoco'])
                c6.metric("☕ Café Tarde", regra_atual['cafe_t'])
                
                st.subheader("🗓️ Cronograma de Produção")
                st.table(r['df']) 
            else: st.warning("Adicione modelos na tabela.")
    else: st.error("⚠️ Erro na Planilha.")
except Exception as e: st.error(f"Erro Crítico: {e}")
