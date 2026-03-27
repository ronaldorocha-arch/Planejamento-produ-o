import streamlit as st
import pandas as pd
import math
import requests
from datetime import datetime, timedelta

# Configuração da página
st.set_page_config(page_title="Planejamento de Produção - NHS", page_icon="🏭", layout="wide")

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
    "ACS - 01": {"cafe_m": "09:50", "almoco": "11:45", "cafe_t": "15:50", "n_nat": 3},
}

# --- FUNÇÃO DE CLIMA CORRIGIDA ---
def pegar_clima():
    try:
        # Puxa temperatura e condição (ex: Sol, Chuva) em português
        url = "https://wttr.in/Curitiba?format=%c+%t+%C&lang=pt"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            texto = response.text.strip()
            # Limpa caracteres especiais de codificação
            return texto.encode('latin1').decode('utf8')
        return "Clima indisponível"
    except:
        return "Clima indisponível"

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
                    'CEL_ORIGEM': celula_atual, 
                    'DISPLAY': f"[{celula_atual}] {modelo} - {descricao} ({int(unidade)} pç/h)"
                })
        return pd.DataFrame(lista_final)
    except Exception as e:
        st.error(f"Erro na leitura: {e}"); return pd.DataFrame()

def gerar_grade_fixa(h_ini_input, regras, tem_gin):
    def para_min(h_str):
        h, m = map(int, h_str.split(':'))
        return h * 60 + m
    m_cafe_m = para_min(regras['cafe_m'])
    m_alm_i, m_alm_f = para_min("11:30"), para_min("12:30")
    m_cafe_t = para_min(regras['cafe_t'])
    m_gin = para_min("09:30")
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    pontos = [h_ini_input] + [m for m in marcos if para_min(m) > para_min(h_ini_input)]
    grade = []
    for i in range(len(pontos)-1):
        p_i, p_f = para_min(pontos[i]), para_min(pontos[i+1])
        is_alm = (p_i == m_alm_i and p_f == m_alm_f)
        min_u = 0
        if not is_alm:
            for m in range(p_i, p_f):
                if not ((m_cafe_m <= m < m_cafe_m+10) or (m_cafe_t <= m < m_cafe_t+10) or (tem_gin and m_gin <= m < m_gin+10) or (m_alm_i <= m < m_alm_f)):
                    min_u += 1
        grade.append({'Horário': f"{pontos[i]} – {pontos[i+1]}", 'Minutos': min_u, 'Label': "🍱 INTERVALO DE ALMOÇO" if is_alm else None})
    return pd.DataFrame(grade)

def calcular(df_in, df_ba, h_ini, n_dia, tem_gin, regra_destino, nome_cel_destino):
    slots = gerar_grade_fixa(h_ini, regra_destino, tem_gin)
    df_in = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA', 'CEL_ORIGEM']], left_on='Equipamento', right_on='DISPLAY', how='left')
    def aplicar_conversao(row):
        u_b = row['UNIDADE_HORA']
        orig = row['CEL_ORIGEM']
        n_orig = REGRAS_HORARIOS.get(orig, {"n_nat": regra_destino['n_nat']})['n_nat']
        return (u_b / n_orig) * n_dia
    df_in['CAD_R'] = df_in.apply(aplicar_conversao, axis=1)
    df_in['T_PC'] = 60 / df_in['CAD_R']
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'], errors='coerce').fillna(0)
    total_d, res, acum, c_idx, tot = df_in['FALTA'].sum(), [], 0.0, 0, 0
    termino = "Não finalizado"
    for _, s in slots.iterrows():
        if s['Label']:
            res.append({'Horário': s['Horário'], 'Modelos': s['Label'], 'Peças': 0, 'Acumulada': tot})
            continue
        acum += s['Minutos']
        p_b, mods = 0, []
        while c_idx < len(df_in):
            t_p = df_in.loc[c_idx, 'T_PC']
            if pd.isna(t_p) or t_p <= 0: c_idx += 1; continue
            if acum >= (t_p - 0.001):
                q = min(math.floor(acum / t_p + 0.001), df_in.loc[c_idx, 'FALTA'])
                if q > 0:
                    acum -= (q * t_p); df_in.loc[c_idx, 'FALTA'] -= q
                    tot += q; p_b += q
                    mods.append(f"{df_in.loc[c_idx, 'ID']} ({int(q)} pçs)")
                if df_in.loc[c_idx, 'FALTA'] <= 0: c_idx += 1
                else: break
            else: break
        res.append({'Horário': s['Horário'], 'Modelos': " + ".join(mods) if mods else "-", 'Peças': int(p_b), 'Acumulada': int(tot)})
        if tot >= total_d and termino == "Não finalizado" and total_d > 0:
            m_u = s['Minutos'] - acum
            h_s, m_s = s['Horário'].split(' – ')[0].split(':')
            dt_b = datetime.strptime(f"{h_s}:{m_s}", "%H:%M") + timedelta(minutes=m_u)
            termino = dt_b.strftime("%H:%M")
    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
try:
    base = carregar_base()
    if not base.empty:
        st.sidebar.markdown("### Tecnologia de Processos")
        st.sidebar.title("📋 Planejamento NHS")
        
        lista_ups = sorted(base['CEL_ORIGEM'].unique().tolist())
        # FORÇA COMEÇAR NA UPS - 1
        idx_inicial = lista_ups.index("UPS - 1") if "UPS - 1" in lista_ups else 0
        
        sel_ups = st.sidebar.selectbox("Selecionar Célula de Trabalho", lista_ups, index=idx_inicial)
        regra_atual = next((v for k, v in REGRAS_HORARIOS.items() if k in sel_ups), REGRAS_HORARIOS["UPS - 1"])
        
        liberar_modelos = st.sidebar.checkbox("🔓 Ver modelos de outras UPS?", value=False)
        h_ini = st.sidebar.text_input("Início da Produção", value="07:45")
        tem_gin = st.sidebar.checkbox("Haverá Ginástica Laboral?", value=False)
        n_dia = st.sidebar.number_input(f"Nº de Pessoas hoje na {sel_ups}", value=regra_atual['n_nat'], min_value=1)

        opcoes = sorted(base['DISPLAY'].tolist()) if liberar_modelos else sorted(base[base['CEL_ORIGEM'] == sel_ups]['DISPLAY'].tolist())

        # CABEÇALHO COM CLIMA AO LADO DOS BOTÕES
        col_tit, col_clim, col_btn = st.columns([0.5, 0.3, 0.2])
        with col_tit: st.header(f"📋 Planejamento: {sel_ups}")
        with col_clim: st.write(f"📍 Curitiba: **{pegar_clima()}**")
        with col_btn:
            if st.button("🗑️ Limpar"):
                st.session_state["reset_key"] = st.session_state.get("reset_key", 0) + 1
                st.rerun()

        df_editor = st.data_editor(pd.DataFrame(columns=["Equipamento", "Qtd"]), num_rows="dynamic", use_container_width=True,
            column_config={"Equipamento": st.column_config.SelectboxColumn("Modelo", options=opcoes, required=True), "Qtd": st.column_config.NumberColumn("Qtd", min_value=0, default=0)}, 
            key=f"ed_{sel_ups}_{st.session_state.get('reset_key', 0)}")

        if st.button("🚀 Gerar Planejamento"):
            if not df_editor.empty:
                r = calcular(df_editor, base, h_ini, n_dia, tem_gin, regra_atual, sel_ups)
                st.divider()
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Planejado", f"{int(r['tot'])} pçs")
                c2.metric("Término Estimado", r['termino'])
                c3.metric("Lotação da Linha", f"{n_dia} pessoas")
                st.subheader("🗓️ Cronograma de Produção")
                st.dataframe(r['df'].style.apply(lambda row: ['background-color: #fff3cd; color: #856404; font-weight: bold'] * len(row) if "🍱" in str(row.Modelos) else [''] * len(row), axis=1), use_container_width=True)
            else: st.warning("Adicione modelos.")
    else: st.error("⚠️ Verifique a planilha.")
except Exception as e: st.error(f"Erro Crítico: {e}")
