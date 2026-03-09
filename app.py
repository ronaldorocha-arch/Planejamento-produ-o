import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta

# Configuração da página (DEVE SER A PRIMEIRA LINHA DE CÓDIGO)
st.set_page_config(page_title="Planejador de Produção", page_icon="🏭", layout="wide")

GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

def gerar_grade_flexivel(hora_inicio_str):
    formato = "%H:%M"
    dia_semana = datetime.now().weekday()
    tem_ginastica_hoje = dia_semana in [0, 2] # Segunda (0) e Quarta (2)
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    minutos_padrao = [50, 60, 60, 0, 60, 60, 50, 60, 60]

    try:
        inicio = datetime.strptime(hora_inicio_str, formato)
    except:
        inicio = datetime.strptime("07:30", formato)

    grade = []
    tempo_atual = inicio

    for i, m_str in enumerate(marcos):
        marco_dt = datetime.strptime(m_str, formato)
        if marco_dt > tempo_atual:
            duracao = (marco_dt - tempo_atual).seconds // 60
            if (tempo_atual <= datetime.strptime("09:00", formato) < marco_dt) or \
               (tempo_atual <= datetime.strptime("15:00", formato) < marco_dt):
                duracao -= 10
            grade.append({'Horário': f"{tempo_atual.strftime(formato)}–{m_str}", 'Minutos úteis': max(0, duracao)})
            for j in range(i, len(marcos) - 1):
                intervalo = f"{marcos[j]}–{marcos[j+1]}"
                mins = minutos_padrao[j]
                if tem_ginastica_hoje and intervalo == "09:30–10:30":
                    mins -= 10
                grade.append({'Horário': intervalo, 'Minutos úteis': mins})
            break
    return pd.DataFrame(grade), tem_ginastica_hoje

def run_production_planning(df_input, hora_inicio):
    time_slots_df, houve_ginastica = gerar_grade_flexivel(hora_inicio)
    try:
        n_nat = pd.to_numeric(str(df_input.iloc[0, 3]).replace(',', '.'), errors='coerce')
        n_dia = pd.to_numeric(str(df_input.iloc[0, 4]).replace(',', '.'), errors='coerce')
        fator = n_dia / n_nat if n_nat > 0 else 1.0
    except: fator = 1.0

    models_df = df_input.iloc[:, :3].copy()
    models_df.columns = ['MODELO', 'CADENCIA_BASE', 'QTD_TOTAL']
    models_df = models_df.dropna(subset=['MODELO'])
    models_df['CADENCIA_REAL'] = pd.to_numeric(models_df['CADENCIA_BASE'], errors='coerce') * fator
    models_df['QTD_OK'] = pd.to_numeric(models_df['QTD_TOTAL'], errors='coerce')
    models_df['Tempo por peça'] = (60 / models_df['CADENCIA_REAL'])
    models_df['Quantidade produzida'] = 0

    results, tempo_acumulado, current_model_index, total_produced = [], 0.0, 0, 0
    total_desired = models_df['QTD_OK'].sum()

    for _, slot in time_slots_df.iterrows():
        horario, tempo_bloco = slot['Horário'], slot['Minutos úteis']
        if tempo_bloco == 0:
            results.append({'Horário': horario, 'Modelos produzidos': 'ALMOÇO', 'Peças no Horário': 0, 'Produção Acumulada': total_produced, 'Sobra': 0})
            continue

        tempo_acumulado += tempo_bloco
        pecas_bloco, modelos_bloco = 0, []

        while current_model_index < len(models_df):
            idx = current_model_index
            t_peca = models_df.loc[idx, 'Tempo por peça']
            falta = models_df.loc[idx, 'QTD_OK'] - models_df.loc[idx, 'Quantidade produzida']
            if falta <= 0: current_model_index += 1; continue

            if tempo_acumulado >= (t_peca - 0.01):
                qtd = min(math.floor(tempo_acumulado / t_peca + 0.01), falta)
                tempo_acumulado -= (qtd * t_peca)
                models_df.loc[idx, 'Quantidade produzida'] += qtd
                total_produced += qtd
                pecas_bloco += qtd
                modelos_bloco.append(f"{models_df.loc[idx, 'MODELO']} ({int(qtd)} pçs)")
                if models_df.loc[idx, 'Quantidade produzida'] >= models_df.loc[idx, 'QTD_OK']: current_model_index += 1
            else: break

        results.append({'Horário': horario, 'Modelos produzidos': " + ".join(modelos_bloco) if modelos_bloco else "Nenhum", 'Peças no Horário': int(pecas_bloco), 'Produção Acumulada': int(total_produced), 'Sobra': round(tempo_acumulado, 2)})

    results_df = pd.DataFrame(results)

    if total_produced >= total_desired:
        last_slot = results_df[results_df['Peças no Horário'] > 0].iloc[-1]
        hora_fim_slot = datetime.strptime(last_slot['Horário'].split('–')[1], '%H:%M')
        finish_dt = hora_fim_slot - timedelta(minutes=last_slot['Sobra'])
        finish_time_str = finish_dt.strftime('%H:%M')
    else:
        finish_time_str = "Incompleto"

    return {'results_df': results_df, 'total': total_produced, 'finish_time': finish_time_str, 'fator': fator, 'ginastica': houve_ginastica}

# --- INTERFACE STREAMLIT ---
st.title("🏭 Planejador de Produção")

st.sidebar.header("Parâmetros")
h_entrada = st.sidebar.text_input("Horário de Início (HH:MM)", value="07:12")

if st.sidebar.button("🔄 Atualizar Dados"):
    st.cache_data.clear()

try:
    df_raw = pd.read_csv(GOOGLE_SHEET_URL)
    res = run_production_planning(df_raw, h_entrada)

    c1, c2, c3 = st.columns(3)
    c1.metric("Eficiência Real", f"{res['fator']:.2%}")
    c2.metric("Ginástica Hoje?", "SIM" if res['ginastica'] else "NÃO")
    c3.metric("Término Estimado", res['finish_time'])

    st.divider()

    st.subheader("Grade de Horários")
    df_web = res['results_df'][['Horário', 'Peças no Horário', 'Produção Acumulada', 'Modelos produzidos']]
    st.dataframe(df_web, use_container_width=True, hide_index=True)

except Exception as e:
    st.error(f"Erro ao carregar dados: {e}")
