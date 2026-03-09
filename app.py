import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta
import plotly.express as px

st.set_page_config(page_title="Planejador NHS", page_icon="🏭", layout="wide")

URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

@st.cache_data(ttl=60)
def carregar_base():
    # Lê a planilha bruta sem pular colunas
    df_raw = pd.read_csv(URL_BASE)
    
    # Limpa nomes de colunas (tira espaços e coloca em maiúsculo)
    df_raw.columns = [str(c).strip().upper() for c in df_raw.columns]
    
    # Lista de colunas que precisamos encontrar
    cols_necessarias = ['MODELO', 'UNIDADE HORA']
    
    # Verifica se as colunas básicas existem
    for c in cols_necessarias:
        if c not in df_raw.columns:
            # Se não achou pelo nome, tenta achar a coluna que CONTÉM o nome
            for real_col in df_raw.columns:
                if c in real_col:
                    df_raw.rename(columns={real_col: c}, inplace=True)
                    break
    
    # A última coluna ou a coluna 'CELULA' (UPS)
    col_ups = 'CELULA'
    if col_ups not in df_raw.columns:
        # Se você não criou o nome 'CELULA', ele tenta pegar a última coluna com dados
        df_raw.rename(columns={df_raw.columns[-1]: col_ups}, inplace=True)

    # Cria o DataFrame de trabalho limpando linhas vazias
    df = df_raw[[ 'MODELO', 'UNIDADE HORA', 'CELULA' ]].copy()
    
    # Remove linhas onde o modelo é nulo ou a unidade hora não é número
    df['MODELO'] = df['MODELO'].astype(str).str.strip()
    df = df[df['MODELO'] != 'nan']
    df['UNIDADE HORA'] = pd.to_numeric(df['UNIDADE HORA'], errors='coerce')
    
    # Preenchimento automático da UPS (ffill)
    df['CELULA'] = df['CELULA'].replace('nan', None).ffill()
    
    return df.dropna(subset=['UNIDADE HORA', 'CELULA'])

# --- LÓGICA DE GRADE E CÁLCULO ---
def gerar_grade_flexivel(hora_inicio_str):
    formato = "%H:%M"
    dia_semana = datetime.now().weekday()
    tem_ginastica_hoje = dia_semana in [0, 2]
    marcos = ["08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30"]
    minutos_padrao = [50, 60, 60, 0, 60, 60, 50, 60, 60]
    try:
        inicio = datetime.strptime(hora_inicio_str, formato)
    except:
        inicio = datetime.strptime("07:12", formato)
    grade, tempo_atual = [], inicio
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
                if tem_ginastica_hoje and intervalo == "09:30–10:30": mins -= 10
                grade.append({'Horário': intervalo, 'Minutos úteis': mins})
            break
    return pd.DataFrame(grade), tem_ginastica_hoje

def run_calculation(df_input, df_base, hora_inicio, fator):
    time_slots_df, houve_ginastica = gerar_grade_flexivel(hora_inicio)
    models_df = df_input.merge(df_base, on='MODELO', how='left')
    models_df['CADENCIA_REAL'] = models_df['UNIDADE HORA'] * fator
    models_df['Tempo_peca'] = 60 / models_df['CADENCIA_REAL']
    models_df['QTD_RESTANTE'] = pd.to_numeric(models_df['Qtd'], errors='coerce').fillna(0)
    
    results, tempo_acumulado, current_idx, total_produced = [], 0.0, 0, 0
    for _, slot in time_slots_df.iterrows():
        horario, tempo_bloco = slot['Horário'], slot['Minutos úteis']
        if tempo_bloco == 0:
            results.append({'Horário': horario, 'Peças': 0, 'Acumulada': total_produced})
            continue
        tempo_acumulado += tempo_bloco
        pecas_bloco = 0
        while current_idx < len(models_df):
            t_peca = models_df.loc[current_idx, 'Tempo_peca']
            if pd.isna(t_peca) or t_peca <= 0: current_idx += 1; continue
            if tempo_acumulado >= (t_peca - 0.01):
                qtd = min(math.floor(tempo_acumulado / t_peca + 0.01), models_df.loc[current_idx, 'QTD_RESTANTE'])
                if qtd > 0:
                    tempo_acumulado -= (qtd * t_peca)
                    models_df.loc[current_idx, 'QTD_RESTANTE'] -= qtd
                    total_produced += qtd
                    pecas_bloco += qtd
                if models_df.loc[current_idx, 'QTD_RESTANTE'] <= 0: current_idx += 1
                else: break
            else: break
        results.append({'Horário': horario, 'Peças': int(pecas_bloco), 'Acumulada': int(total_produced)})
    return {'df': pd.DataFrame(results), 'total': total_produced, 'ginastica': houve_ginastica}

# --- INTERFACE ---
try:
    df_base_total = carregar_base()
    
    st.sidebar.title("⚙️ Painel de Controle")
    lista_ups = sorted(df_base_total['CELULA'].unique().tolist())
    ups_selecionada = st.sidebar.selectbox("Escolha a Célula", lista_ups)
    
    h_inicio = st.sidebar.text_input("Hora de Início", value="07:12")
    
    st.sidebar.markdown("---")
    n_nat = st.sidebar.number_input("N Natural", value=3, min_value=1)
    n_dia = st.sidebar.number_input("N do Dia", value=3, min_value=1)
    fator = n_dia / n_nat

    df_ups = df_base_total[df_base_total['CELULA'] == ups_selecionada]
    opcoes_modelos = sorted(df_ups['MODELO'].unique().tolist())

    st.header(f"📋 Programação: {ups_selecionada}")
    
    df_editor = st.data_editor(
        pd.DataFrame([{"MODELO": opcoes_modelos[0], "Qtd": 0}]),
        num_rows="dynamic", use_container_width=True,
        column_config={
            "MODELO": st.column_config.SelectboxColumn("Modelo", options=opcoes_modelos, required=True),
            "Qtd": st.column_config.NumberColumn("Qtd", min_value=0)
        }
    )

    if st.button("🚀 Calcular Planejamento"):
        res = run_calculation(df_editor, df_ups, h_inicio, fator)
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Peças Totais", f"{int(res['total'])} pçs")
        c2.metric("Eficiência Real", f"{fator:.2%}")
        c3.metric("Ginástica", "SIM" if res['ginastica'] else "NÃO")
        
        fig = px.bar(res['df'], x='Horário', y='Peças', text='Peças', title="Volume por Horário", color_discrete_sequence=['#007BFF'])
        st.plotly_chart(fig, use_container_width=True)
        st.table(res['df'])

except Exception as e:
    st.error(f"Erro ao processar planilha: {e}")
    st.info("Certifique-se de que os títulos MODELO e UNIDADE HORA estão escritos corretamente na planilha.")
