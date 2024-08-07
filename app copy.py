import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from dateutil.parser import parse

st.set_page_config(page_title="Análise de Vendas Avançada", layout="wide")

st.title("Análise de Vendas Avançada")

# Função para calcular RFM
def calculate_rfm(df):
    today = df['Data da Venda'].max()
    rfm = df.groupby('ID do Cliente').agg({
        'Data da Venda': lambda x: (today - x.max()).days,
        'ID do Cliente': 'count',
        'Valor da Venda': 'sum'
    })
    rfm.columns = ['Recency', 'Frequency', 'Monetary']
    return rfm

# Função para calcular coortes
def calculate_cohorts(df, period):
    # Determine the cohort for each customer (first purchase date)
    df['CohortDate'] = df.groupby('ID do Cliente')['Data da Venda'].transform('min').dt.to_period(period)
    
    # Calculate the periods since first purchase for each transaction
    if period == 'W':
        df['Periods'] = ((df['Data da Venda'] - df['CohortDate'].dt.to_timestamp()).dt.days / 7).fillna(0).astype(int)
    elif period == 'M':
        df['Periods'] = ((df['Data da Venda'].dt.to_period('M').astype(int) - 
                          df['CohortDate'].astype(int))).fillna(0).astype(int)
    elif period == 'Q':
        df['Periods'] = ((df['Data da Venda'].dt.to_period('Q').astype(int) - 
                          df['CohortDate'].astype(int))).fillna(0).astype(int)
    elif period == 'Y':
        df['Periods'] = (df['Data da Venda'].dt.year - 
                         df['CohortDate'].dt.year.fillna(0).astype(int)).fillna(0).astype(int)
    
    # Get the max period for each customer in each cohort
    cohort_data = df.groupby(['CohortDate', 'ID do Cliente'])['Periods'].max().reset_index()
    
    # Calculate retention for each cohort and period
    cohort_counts = cohort_data.groupby(['CohortDate', 'Periods']).size().unstack(fill_value=0)
    cohort_sizes = cohort_counts.iloc[:, 0]
    retention = cohort_counts.divide(cohort_sizes, axis=0)
    
    # Ensure all cohorts start from period 0
    all_periods = range(retention.columns.max() + 1)
    retention = retention.reindex(columns=all_periods, fill_value=np.nan)
    
    # Fill in retention rates, ensuring they only decrease
    for cohort in retention.index:
        retention.loc[cohort, 0] = 1.0  # Start at 100%
        for period in range(1, len(all_periods)):
            if pd.isna(retention.loc[cohort, period]):
                retention.loc[cohort, period] = retention.loc[cohort, period-1]
            else:
                retention.loc[cohort, period] = min(retention.loc[cohort, period], retention.loc[cohort, period-1])
    
    # Convert index to string for compatibility with Plotly
    retention.index = retention.index.astype(str)
    
    return retention

# Função para calcular receita cumulativa por coorte
def calculate_cumulative_revenue(df, period):
    df['CohortDate'] = df.groupby('ID do Cliente')['Data da Venda'].transform('min').dt.to_period(period)
    
    if period == 'W':
        df['Period'] = ((df['Data da Venda'] - df['CohortDate'].dt.to_timestamp()).dt.days // 7).fillna(0).astype(int)
    elif period == 'M':
        df['Period'] = ((df['Data da Venda'].dt.to_period('M').astype(int) - 
                         df['CohortDate'].astype(int))).fillna(0).astype(int)
    elif period == 'Q':
        df['Period'] = ((df['Data da Venda'].dt.to_period('Q').astype(int) - 
                         df['CohortDate'].astype(int))).fillna(0).astype(int)
    elif period == 'Y':
        df['Period'] = (df['Data da Venda'].dt.year - 
                        df['CohortDate'].dt.year.fillna(0).astype(int)).fillna(0).astype(int)
    
    # Ensure all periods start from 0
    df['Period'] = df.groupby('CohortDate')['Period'].transform(lambda x: x - x.min())
    
    # Calculate cumulative revenue
    cumulative_revenue = df.groupby(['CohortDate', 'ID do Cliente', 'Period'])['Valor da Venda'].sum().unstack(fill_value=0).cumsum(axis=1)
    median_cumulative_revenue = cumulative_revenue.groupby('CohortDate').median()
    
    # Ensure all cohorts have the same number of periods
    max_periods = int(median_cumulative_revenue.columns.max())  # Convert to int
    all_periods = range(max_periods + 1)
    median_cumulative_revenue = median_cumulative_revenue.reindex(columns=all_periods, fill_value=np.nan)
    
    # Fill NaN values with the last known value to create a flat line
    median_cumulative_revenue = median_cumulative_revenue.fillna(method='ffill', axis=1)
    
    return median_cumulative_revenue

# Função para detectar o formato da data
def detect_date_format(date_string):
    formats_to_try = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
        '%d/%m/%Y',
        '%d-%m-%Y',
        '%m/%d/%Y',
        '%d.%m.%Y',
        '%Y/%m/%d'
    ]
    for fmt in formats_to_try:
        try:
            parse(date_string, parserinfo=None)
            return fmt
        except ValueError:
            pass
    return None

# Função para converter datas
def convert_dates(df, date_column):
    # Remover linhas onde a data é NaN
    df = df.dropna(subset=[date_column])
    
    try:
        # Tentar converter para datetime
        df[date_column] = pd.to_datetime(df[date_column], errors='coerce')
        
        # Extrair apenas a data (ano, mês, dia)
        df[date_column] = df[date_column].dt.date
        
        # Remover linhas onde a conversão falhou (resultou em NaT)
        df = df.dropna(subset=[date_column])
        
    except Exception as e:
        st.error(f"Erro ao converter datas: {str(e)}")
        st.stop()
    
    return df

# Upload do arquivo
uploaded_file = st.file_uploader("Escolha um arquivo CSV ou XLSX", type=["csv", "xlsx"])

if uploaded_file is not None:
    # Leitura do arquivo
    file_type = uploaded_file.name.split('.')[-1]
    if file_type == 'csv':
        df = pd.read_csv(uploaded_file)
    elif file_type == 'xlsx':
        df = pd.read_excel(uploaded_file)
    
    # Seleção de colunas
    st.subheader("Seleção de Colunas")
    id_column = st.selectbox("Selecione a coluna para ID do Cliente", df.columns)
    date_column = st.selectbox("Selecione a coluna para Data da Venda", df.columns)
    
    # Renomeação das colunas
    df = df.rename(columns={id_column: 'ID do Cliente', date_column: 'Data da Venda'})
    
    # Conversão da data
    if date_column:
        df = convert_dates(df, 'Data da Venda')
        
        # Verificar se ainda existem datas válidas após a conversão
        if not df['Data da Venda'].empty:
            min_date = df['Data da Venda'].min()
            max_date = df['Data da Venda'].max()
            
            # Filtro de data
            start_date, end_date = st.sidebar.date_input(
                "Intervalo de Datas",
                [min_date, max_date],
                min_value=min_date,
                max_value=max_date
            )
        else:
            st.error("Não foi possível converter as datas. Por favor, verifique o formato da coluna de data.")
            st.stop()
    else:
        st.error("Por favor, selecione uma coluna de data válida.")
        st.stop()
    
    # Verificar se a coluna 'Valor da Venda' já existe
    if 'Valor da Venda' not in df.columns:
        # Opção para escolher como calcular o Valor da Venda
        valor_venda_opcao = st.radio(
            "Como você quer definir o Valor da Venda?",
            ("Selecionar coluna", "Usar fórmula")
        )

        if valor_venda_opcao == "Selecionar coluna":
            value_column = st.selectbox("Selecione a coluna para Valor da Venda", df.columns)
            df['Valor da Venda'] = df[value_column]
        else:
            # Seleção de colunas para o cálculo do Valor da Venda
            st.subheader("Cálculo do Valor da Venda")
            value_columns = st.multiselect("Selecione as colunas para o cálculo do Valor da Venda", df.columns)

            # Criação de inputs para cada coluna selecionada
            column_inputs = {}
            for col in value_columns:
                column_inputs[col] = st.text_input(f"Alias para {col}", col)

            # Input para a fórmula
            formula = st.text_input("Fórmula para o Valor da Venda (use os aliases e operadores +, -, *, /, e parênteses)", "")

            # Botão para aplicar a fórmula
            if st.button("Aplicar Fórmula"):
                try:
                    # Criar um dicionário com os aliases e os valores das colunas
                    data = {alias: df[col] for col, alias in column_inputs.items()}
                    
                    # Substituir os aliases na fórmula pelos nomes das variáveis no dicionário
                    for alias in column_inputs.values():
                        formula = formula.replace(alias, f"data['{alias}']")
                    
                    # Avaliar a fórmula
                    df['Valor da Venda'] = eval(formula)
                    
                    st.success("Fórmula aplicada com sucesso!")
                except Exception as e:
                    st.error(f"Erro ao aplicar a fórmula: {str(e)}")
                    st.stop()

    # Garantir que a coluna 'Valor da Venda' existe antes de continuar
    if 'Valor da Venda' not in df.columns:
        st.error("A coluna 'Valor da Venda' não foi definida. Por favor, defina-a antes de continuar.")
        st.stop()
    
    # Aplicar filtros
    mask = (df['Data da Venda'] >= start_date) & (df['Data da Venda'] <= end_date)
    filtered_df = df.loc[mask, ['ID do Cliente', 'Data da Venda', 'Valor da Venda']]
    
    # Métricas principais
    st.markdown("""
    <style>
    .big-font {
        font-size:30px !important;
        font-weight: bold;
    }
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .metric-label {
        font-size: 14px;
        color: #555;
    }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.markdown(
            f"""
            <div class="metric-card">
                <p class="metric-label">Total de Vendas</p>
                <p class="big-font">R$ {filtered_df['Valor da Venda'].sum():,.0f}</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col2:
        st.markdown(
            f"""
            <div class="metric-card">
                <p class="metric-label">Número de Vendas</p>
                <p class="big-font">{len(filtered_df):,}</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col3:
        st.markdown(
            f"""
            <div class="metric-card">
                <p class="metric-label">Ticket Médio</p>
                <p class="big-font">R$ {filtered_df['Valor da Venda'].mean():,.0f}</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col4:
        st.markdown(
            f"""
            <div class="metric-card">
                <p class="metric-label">Clientes Únicos</p>
                <p class="big-font">{filtered_df['ID do Cliente'].nunique():,}</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col5:
        st.markdown(
            f"""
            <div class="metric-card">
                <p class="metric-label">Frequência Média</p>
                <p class="big-font">{filtered_df.groupby('ID do Cliente').size().mean():.2f}</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Gráfico de vendas (novos vs recorrentes)
    st.subheader("Vendas: Novos vs Recorrentes")
    
    # Opções de agregação
    agg_options = {
        "Semanal": "W",
        "Mensal": "M",
        "Trimestral": "Q",
        "Anual": "Y"
    }

    # Seleção do nível de agregação (agora no sidebar para ser global)
    aggregation = st.sidebar.selectbox("Selecione o nível de agregação para toda a análise", list(agg_options.keys()))

    # Garantir que 'Data da Venda' seja datetime
    filtered_df['Data da Venda'] = pd.to_datetime(filtered_df['Data da Venda'])

    # Identificar clientes novos vs recorrentes
    filtered_df['FirstPurchase'] = filtered_df.groupby('ID do Cliente')['Data da Venda'].transform('min')
    filtered_df['CustomerType'] = np.where(filtered_df['Data da Venda'] == filtered_df['FirstPurchase'], 'Novo', 'Recorrente')

    # Função para agregar dados
    def aggregate_data(df, aggregation):
        return df.set_index('Data da Venda').groupby([pd.Grouper(freq=agg_options[aggregation]), 'CustomerType'])['Valor da Venda'].sum().unstack(fill_value=0)

    # Agregar vendas
    sales_agg = aggregate_data(filtered_df, aggregation)

    # Criar gráfico
    fig = px.bar(sales_agg, 
                 x=sales_agg.index, 
                 y=['Novo', 'Recorrente'], 
                 title=f'Vendas por {aggregation} (Novos vs Recorrentes)',
                 labels={'value': 'Valor de Vendas', 'Data da Venda': 'Data'},
                 barmode='stack')

    st.plotly_chart(fig)

    # Calcular e exibir métricas
    total_new = sales_agg['Novo'].sum()
    total_recurring = sales_agg['Recorrente'].sum()
    total_sales = total_new + total_recurring

    st.markdown(f"""
    ### Métricas de Vendas
    - Total de Vendas para Novos Clientes: R$ {total_new:,.2f} ({total_new/total_sales:.1%})
    - Total de Vendas para Clientes Recorrentes: R$ {total_recurring:,.2f} ({total_recurring/total_sales:.1%})
    - Total de Vendas: R$ {total_sales:,.2f}
    """)
    
    # Análise de Coorte
    st.markdown("""
    ### Análise de Coorte
    Este gráfico mostra a retenção de clientes ao longo do tempo. Cada linha representa uma coorte de clientes que fizeram sua primeira compra no mesmo período. O eixo X mostra os períodos subsequentes, e o eixo Y mostra a porcentagem de clientes retidos.
    """)
    st.subheader("Análise de Coorte")
    cohort_period = st.selectbox("Período de Coorte", ("Semanal", "Mensal", "Trimestral", "Anual"))
    cohort_map = {"Semanal": "W", "Mensal": "M", "Trimestral": "Q", "Anual": "Y"}
    cohort_df = calculate_cohorts(filtered_df, cohort_map[cohort_period])
    
    # Heatmap
    fig_cohort_heatmap = px.imshow(cohort_df, 
                                   text_auto='.0%', 
                                   aspect="auto", 
                                   color_continuous_scale='RdYlGn',  # Red-Yellow-Green scale
                                   zmin=0, 
                                   zmax=1)

    fig_cohort_heatmap.update_layout(
        title=f'Retenção de Coorte - Heatmap ({cohort_period})',
        xaxis_title='Períodos',
        yaxis_title='Coorte',
        coloraxis_colorbar=dict(
            title='Taxa de Retenção',
            tickformat='.0%'
        )
    )

    # Ajuste o tamanho da fonte do texto dentro das células
    fig_cohort_heatmap.update_traces(textfont_size=10)

    st.plotly_chart(fig_cohort_heatmap, use_container_width=True)
    
    # Line chart
    cohort_df_melted = cohort_df.reset_index().melt(id_vars='CohortDate', var_name='Period', value_name='Retention')
    cohort_df_melted = cohort_df_melted.dropna()  # Remove NaN values
    fig_cohort_line = px.line(cohort_df_melted, x='Period', y='Retention', color='CohortDate', 
                              title=f'Retenção de Coorte - Linhas ({cohort_period})')

    # Add median line
    median_retention = cohort_df_melted.groupby('Period')['Retention'].median()
    fig_cohort_line.add_scatter(x=median_retention.index, y=median_retention.values, mode='lines', 
                                name='Mediana', line=dict(color='black', dash='dash'))

    # Update y-axis to show percentages and set range from 0 to 100%
    fig_cohort_line.update_layout(yaxis_tickformat='.0%', yaxis_range=[0, 1])

    st.plotly_chart(fig_cohort_line, use_container_width=True)
    
    # Análise de receita cumulativa por coorte
    st.markdown("""
    ### Receita Cumulativa por Coorte
    Este gráfico mostra a receita cumulativa mediana por cliente para cada coorte ao longo do tempo. Cada linha representa uma coorte de clientes que fizeram sua primeira compra no mesmo período. O eixo X mostra os períodos subsequentes, e o eixo Y mostra a receita cumulativa mediana.
    """)
    cumulative_revenue_df = calculate_cumulative_revenue(filtered_df, cohort_map[cohort_period])
    fig_cumulative_revenue = px.line(cumulative_revenue_df.reset_index().melt(id_vars='CohortDate', var_name='Period', value_name='Cumulative Revenue'),
                                     x='Period', y='Cumulative Revenue', color='CohortDate',
                                     title=f'Receita Cumulativa Mediana por Cliente por Coorte ({cohort_period})',
                                     labels={'Period': 'Período', 'Cumulative Revenue': 'Receita Cumulativa Mediana (R$)'},
                                     hover_data={'Cumulative Revenue': ':,.2f'})
    fig_cumulative_revenue.update_traces(mode='lines+markers')
    fig_cumulative_revenue.update_layout(hovermode='x unified')
    st.plotly_chart(fig_cumulative_revenue, use_container_width=True)
    
    # Análise RFM
    st.markdown("""
    ### Segmentação RFM
    Este gráfico de árvore mostra a distribuição de clientes em diferentes segmentos com base em sua Recência (R), Frequência (F) e Valor Monetário (M).

    - **New Customers**: Clientes que fizeram uma compra recentemente, mas têm baixa frequência.
    - **Best Customers**: Clientes com alta recência, frequência e valor monetário.
    - **Loyal Customers**: Clientes com boa recência, frequência e valor monetário.
    - **Lost Customers**: Clientes que não compraram recentemente, têm baixa frequência e baixo valor monetário.
    - **Lost Cheap Customers**: Clientes que não compraram há muito tempo, têm baixa frequência e baixo valor monetário.
    - **Other**: Clientes que não se encaixam nas categorias acima.

    Cada retngulo representa um segmento, e o tamanho do retângulo é proporcional ao número de clientes nesse segmento.
    """)
    st.subheader("Análise RFM")
    rfm = calculate_rfm(filtered_df)
    
    def rfm_segmentation(rfm):
        r_labels = range(4, 0, -1)
        f_labels = range(1, 5)
        m_labels = range(1, 5)
                
        r_quartiles = pd.qcut(rfm['Recency'], q=4, labels=r_labels)
        f_quartiles = pd.qcut(rfm['Frequency'], q=4, labels=f_labels)
        m_quartiles = pd.qcut(rfm['Monetary'], q=4, labels=m_labels)
                
        rfm['R'] = r_quartiles
        rfm['F'] = f_quartiles
        rfm['M'] = m_quartiles
                
        def rfm_segment(row):
            if row['R'] >= 3 and row['F'] == 1:
                return 'New Customers'
            elif row['R'] == 4 and row['F'] == 4 and row['M'] == 4:
                return 'Best Customers'
            elif row['R'] >= 3 and row['F'] >= 3 and row['M'] >= 3:
                return 'Loyal Customers'
            elif row['R'] >= 3 and row['F'] <= 2 and row['M'] <= 2:
                return 'Lost Customers'
            elif row['R'] <= 2 and row['F'] <= 2 and row['M'] <= 2:
                return 'Lost Cheap Customers'
            else:
                return 'Other'
                
        rfm['Segment'] = rfm.apply(rfm_segment, axis=1)
        return rfm

    rfm_segmented = rfm_segmentation(rfm)

    segment_counts = rfm_segmented['Segment'].value_counts()
    fig_rfm = px.treemap(names=segment_counts.index, parents=[""] * len(segment_counts),
                         values=segment_counts.values, title='Segmentaão RFM')
    st.plotly_chart(fig_rfm, use_container_width=True)
    
    # Tabela de dados
    st.subheader("Dados Brutos")
    st.dataframe(filtered_df)

else:
    st.info("Por favor, faça o upload de um arquivo CSV ou XLSX para começar a análise.")