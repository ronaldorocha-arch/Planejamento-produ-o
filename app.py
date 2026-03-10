import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta

st.set_page_config(page_title="Planejador NHS", page_icon="🏭", layout="wide")

URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

# --- CONFIGURAÇÃO DE HORÁRIOS REAIS (Conforme sua lista) ---
REGRAS_HORARIOS = {
    "UPS - 1": {"cafe_m": "09:20", "almoco": "11:30", "cafe_t": "15:20", "n_nat": 5},
    "UPS - 2": {"cafe_m": "09:00", "almoco": "11:30", "cafe_t": "15:00", "n_nat": 3},
    "UPS - 3": {"cafe_m": "09:10", "almoco": "11:50", "cafe_t": "15:10", "n_nat": 3},
    "UPS - 4": {"cafe_m": "09:20", "almoco": "11:45", "cafe_t": "15:10", "n_nat": 3},
    "UPS - 6": {"cafe_m": "09:30", "almoco": "11:45", "cafe_t": "15:30", "n_nat": 4},
    "UPS - 7": {"cafe_m": "09:30", "almoco": "11:45", "cafe_t": "15:40", "n_nat": 4},
    "UPS - 8": {"cafe_m": "09:40", "almoco": "11:45", "cafe_t": "15:40", "n_nat": 4},
    "ACS":     {"cafe_m": "09:50", "almoco": "11:45", "cafe_t": "15:50", "n_nat": 2},
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
            if "UPS" in cel_na_linha or "ACS" in cel_na_linha:
                celula_atual = str(dados.iloc[i, 9]).strip()
            if modelo != 'nan' and len(modelo) > 3 and not pd.isna(unidade):
                lista_final.append({
                    'ID': modelo, 'UNIDADE_HORA': unidade, 'DESCRICAO': descricao,
                    'CELULA': celula_atual, 'DISPLAY': f"{modelo} - {descricao} ({unidade} pç/h)"
                })
        return pd.DataFrame(lista_final)
    except Exception as e:
        st.error(f"Erro na leitura: {e}"); return pd.DataFrame()

def gerar_grade(h_ini, tem_gin, regras):
    fmt = "%H:%M"
    # Marcos de hora em hora para o relatório
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    
    h_cafe_m = datetime.strptime(regras['cafe_m'], fmt)
    h_almoco_ini = datetime.strptime(regras['almoco'], fmt)
    h_almoco_fim = h_almoco_ini + timedelta(minutes=60)
    h_cafe_t = datetime.strptime(regras['cafe_t'], fmt)
    
    try: atual = datetime.strptime(h_ini, fmt)
    except: atual = datetime.strptime("07:12", fmt)
    
    grade = []
    for i, m_s in enumerate(marcos):
        m_dt = datetime.strptime(m_s, fmt)
        if m_dt > atual:
            # Função para calcular minutos úteis entre dois horários
            def calc_uteis(inicio, fim):
                if fim <= inicio: return 0
                tot = (fim - inicio).seconds // 60
                # Desconto Café Manhã
                if inicio <= h_cafe_m < fim: tot -= 10
                # Desconto Café Tarde
                if inicio <= h_cafe_t < fim: tot -= 10
                # Desconto Almoço (60 min)
                # Se o intervalo de almoço sobrepõe o bloco, calcula a sobreposição
                sobreposicao_almoco = max(0, (min(fim, h_almoco_fim) - max(inicio, h_almoco_ini)).seconds // 60)
                tot -= sobreposicao_almoco
                return max(0, tot)

            # Primeiro bloco (do início real até o primeiro marco)
            grade.append({'Horário': f"{atual.strftime(fmt)}–{m_s}", 'Minutos': calc_uteis(atual, m_dt), 'Fim_dt': m_dt})
            
            # Blocos seguintes de 60 min
            for j in range(i, len(marcos) - 1):
                b_ini = datetime.strptime(marcos[j], fmt)
                b_fim = datetime.strptime(marcos[j+1], fmt)
                m_uteis = calc_uteis(b_ini, b_fim)
                
                # Se os minutos úteis forem 0 e estiver no horário de almoço, marca como Almoço
                label = f"{marcos[j]}–{marcos[j+1]}"
                grade.append({'Horário': label, 'Minutos': m_uteis, 'Fim_dt': b_fim})
            break
    return pd.DataFrame(grade)

def calcular(df_in, df_ba, h_ini, fat, tem_gin, regras):
    slots = gerar_grade(h_ini, tem_gin, regras)
    df_in = df_in.merge(df_ba[['DISPLAY', 'ID', 'UNIDADE_HORA']], left_on='Equipamento', right_on='DISPLAY', how='left')
    df_in['CAD_R'] = df_in['UNIDADE_HORA'] * fat
    df_in['T_PC'] = 60 / df_in['CAD_R']
    df_in['FALTA'] = pd.to_numeric(df_in['Qtd'], errors='coerce').fillna(0)
    total_desejado, res, acum, c_idx, tot = df_in['FALTA'].sum(), [], 0.0, 0, 0
    termino = "Incompleto"
    
    for _, s in slots.iterrows():
        hor, t_b, f_dt = s['Horário'], s['Minutos'], s['Fim_dt']
        
        if t_b <= 0:
            res.append({'Horário': hor, 'Modelos': 'INTERVALO/ALMOÇO', 'Peças': 0, 'Acumulada': tot})
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
            # Ajuste do término considerando que 'acum' são os minutos que sobraram no bloco
            minutos_gastos_no_bloco = s['Minutos'] - acum
            # Estimativa simplificada do término real
            termino = (f_dt - timedelta(minutes=int(acum))).strftime("%H:%M")

    return {'df': pd.DataFrame(res), 'tot': tot, 'termino': termino}

# --- INTERFACE ---
try:
    base = carregar_base()
    if not base.empty:
        st.sidebar.title("⚙️ Controle")
        lista_ups = sorted(base['CELULA'].unique().tolist())
        sel_ups = st.sidebar.selectbox("Selecionar Célula", lista_ups)
        
        # Busca a regra. Ex: Se selecionou "UPS - 1", pega a chave "UPS - 1"
        regra_atual = next((v for k, v in REGRAS_HORARIOS.items() if k in sel_ups), REGRAS_HORARIOS["UPS - 1"])
        
        h_ini = st.sidebar.text_input("Início da Produção", value="07:12")
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
                r = calcular(df_editor, base, h_ini, fator, tem_gin, regra_atual)
                st.divider()
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total", f"{int(r['tot'])} pçs")
                m2.metric("Término Real", r['termino'])
                m3.metric("Eficiência N", f"{fator:.2%}")
                m4.metric("Ginástica", "SIM" if tem_gin else "NÃO")
                st.table(r['df'])
            else:
                st.warning("Adicione os modelos na lista.")
    else:
        st.error("⚠️ Estrutura não detectada. Verifique a planilha.")
except Exception as e:
    st.error(f"Erro Crítico: {e}")
