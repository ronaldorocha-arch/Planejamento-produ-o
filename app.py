import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta
import plotly.express as px

st.set_page_config(page_title="Planejador NHS", page_icon="🏭", layout="wide")

# URL da sua planilha (Base de Dados)
URL_BASE = "https://docs.google.com/spreadsheets/d/11-jv_ZFetz9xdbJY8JZwPFSc3gtB65duvtDlLEk4I2E/export?format=csv&gid=0"

@st.cache_data(ttl=600)
def carregar_base():
    # Lê a planilha
    df = pd.read_csv(URL_BASE)
    
    # Ajusta os nomes das colunas conforme sua imagem
    # Coluna 0: MODELO, Coluna 1: UNIDADE HORA, Coluna 3: DESCRIÇÃO, Última: UPS
    df.columns.values[0] = 'MODELO'
    df.columns.values[1] = 'UNIDADE HORA'
    df.columns.values[-1] = 'UPS_BRUTA'
    
    # Preenche as células mescladas da UPS
    df['CÉLULA'] = df['UPS_BRUTA'].fillna(method='ffill')
    
    # Limpeza de dados
    df['MODELO'] = df['MODELO'].astype(str).str.strip()
    df['UNIDADE HORA'] = pd.to_numeric(df['UNIDADE HORA'], errors='coerce')
    
    return df[['MODELO', 'UNIDADE HORA', 'CÉLULA']].dropna(subset=['MODELO'])

def gerar_grade_flexivel(hora_inicio_str):
    formato = "%H:%M"
    dia_semana = datetime.now().weekday()
    tem_ginastica_hoje = dia_semana in [0, 2] # Seg e Qua
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
            # Pausas de café (9h e 15h)
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
    models_df['Tempo por peça'] = 60 / models_df['CADENCIA_REAL']
    models_df['QTD_RESTANTE'] = pd.to_numeric(models_df['QUANTIDADE'], errors='coerce').fillna(0)
    
    results, tempo_acumulado, current_idx, total_produced = [], 0.0, 0, 0
    for _, slot in time_slots_df.iterrows():
        horario, tempo_bloco = slot['Horário'], slot['Minutos úteis']
        if tempo_bloco == 0:
            results.append({'Horário': horario, 'Modelos': 'ALMOÇO', 'Peças': 0, 'Acumulada': total_produced})
            continue
        tempo_acumulado += tempo_bloco
        pecas_bloco, modelos_bloco = 0, []
        while current_idx < len(models_df):
            t_peca = models_df.loc[current_idx, 'Tempo por peça']
            if pd.isna(t_peca) or t_peca <= 0: current_idx += 1; continue
            if tempo_acumulado >= (t_peca - 0.01):
                qtd = min(math.floor(tempo_acumulado / t_peca + 0.01), models_df.loc[current_idx, 'QTD_RESTANTE'])
                if qtd > 0:
                    tempo_acumulado -= (qtd * t_peca)
                    models_df.loc[current_idx, 'QTD_RESTANTE'] -= qtd
                    total_produced += qtd
                    pecas_bloco += qtd
                    modelos_bloco.append(f"{models_df.loc[current_idx, 'MODELO']} ({int(qtd)})")
                if models_df.loc[current_idx, 'QTD_RESTANTE'] <= 0: current_idx += 1
                else: break
            else: break
        results.append({'Horário': horario, 'Modelos': " + ".join(modelos_bloco) if modelos_bloco else "-", 'Peças': int(pecas_bloco), 'Acumulada': int(total_produced)})
    
    return {'df': pd.DataFrame(results), 'total': total_produced, 'ginastica': houve_ginastica}

# --- INTERFACE ---
try:
    df_completo = carregar_base()
    
    st.sidebar.title("⚙️ Painel de Controle")
    lista_ups = sorted(df_completo['CÉLULA'].unique().tolist())
    ups_selecionada = st.sidebar.selectbox("Selecione a Célula (UPS)", lista_ups)
    
    df_filtrado = df_completo[df_completo['CÉLULA'] == ups_selecionada]
    lista_modelos = sorted(df_filtrado['MODELO'].unique().tolist())
    
    h_inicio = st.sidebar.text_input("Hora de Início", value="07:12")
    eficiencia = st.sidebar.number_input("Eficiência da Linha (%)", value=100) / 100

    st.header(f"📋 Planejamento de Produção: {ups_selecionada}")
    
    # Tabela editável
    df_input_template = pd.DataFrame([{"MODELO": lista_modelos[0], "QUANTIDADE": 0}])
    df_usuario = st.data_editor(
        df_input_template,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "MODELO": st.column_config.SelectboxColumn("Modelo do Equipamento", options=lista_modelos, required=True),
            "QUANTIDADE": st.column_config.NumberColumn("Quantidade", min_value=0)
        }
    )

    if st.button("🚀 Calcular e Gerar Gráfico"):
        res = run_calculation(df_usuario, df_filtrado, h_inicio, eficiencia)
        
        st.divider()
        
        # Métricas em colunas
        m1, m2, m3 = st.columns(3)
        m1.metric("Peças Totais", f"{int(res['total'])} pçs")
        m2.metric("Eficiência", f"{eficiencia:.0%}")
        m3.metric("Ginástica", "SIM" if res['ginastica'] else "NÃO")

        # Gráfico de Barras (Plotly)
        df_grafico = res['df'][res['df']['Peças'] > 0]
        if not df_grafico.empty:
            fig = px.bar(df_grafico, x='Horário', y='Peças', 
                         title="Volume de Produção por Horário",
                         text='Peças', color_discrete_sequence=['#00CC96'])
            st.plotly_chart(fig, use_container_width=True)
        
        # Tabela Final
        st.subheader("🗓️ Detalhamento por Faixa Horária")
        st.table(res['df'])

except Exception as e:
    st.error(f"Erro ao carregar os dados. Verifique a planilha: {e}")
