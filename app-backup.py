import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import locale

# Configurar a localização para o português do Brasil
locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')

# Função para formatar números no padrão brasileiro
def format_br(valor):
    return locale.format_string('%.2f', valor, grouping=True)

st.set_page_config(page_title="Análise de Vendas Avançada", layout="wide")

st.title("Análise de Vendas Avançada")

# Função para calcular o Valor da Venda
@st.cache_data
def calculate_sale_value(df, formula, column_inputs):
    try:
        data = {alias: df[col] for col, alias in column_inputs.items()}
        for alias in column_inputs.values():
            formula = formula.replace(alias, f"data['{alias}']")
        df['Valor da Venda'] = eval(formula)
        return df
    except Exception as e:
        st.error(f"Erro ao aplicar a fórmula: {str(e)}")
        return None

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
    df['CohortDate'] = df.groupby('ID do Cliente')['Data da Venda'].transform('min').dt.to_period(period)
    
    if period == 'M':
        df['Periods'] = ((df['Data da Venda'].dt.to_period('M').astype(int) - 
                          df['CohortDate'].astype(int))).fillna(0).astype(int)
    elif period == 'Q':
        df['Periods'] = ((df['Data da Venda'].dt.to_period('Q').astype(int) - 
                          df['CohortDate'].astype(int))).fillna(0).astype(int)
    elif period == 'Y':
        df['Periods'] = (df['Data da Venda'].dt.year - 
                         df['CohortDate'].dt.year.fillna(0).astype(int)).fillna(0).astype(int)
    
    cohort_data = df.groupby(['CohortDate', 'ID do Cliente'])['Periods'].max().reset_index()
    cohort_counts = cohort_data.groupby(['CohortDate', 'Periods']).size().unstack(fill_value=0)
    cohort_sizes = cohort_counts.iloc[:, 0]
    retention = cohort_counts.divide(cohort_sizes, axis=0)
    
    all_periods = range(retention.columns.max() + 1)
    retention = retention.reindex(columns=all_periods, fill_value=np.nan)
    
    for cohort in retention.index:
        retention.loc[cohort, 0] = 1.0
        for period in range(1, len(all_periods)):
            if pd.isna(retention.loc[cohort, period]):
                retention.loc[cohort, period] = retention.loc[cohort, period-1]
            else:
                retention.loc[cohort, period] = min(retention.loc[cohort, period], retention.loc[cohort, period-1])
    
    retention.index = retention.index.astype(str)
    
    return retention

# Função para calcular a receita média cumulativa por cliente
def calculate_cumulative_revenue(df, period):
    df['CohortDate'] = df.groupby('ID do Cliente')['Data da Venda'].transform('min').dt.to_period(period)
    
    if period == 'M':
        df['Periods'] = ((df['Data da Venda'].dt.to_period('M').astype(int) - 
                          df['CohortDate'].astype(int))).fillna(0).astype(int)
    elif period == 'Q':
        df['Periods'] = ((df['Data da Venda'].dt.to_period('Q').astype(int) - 
                          df['CohortDate'].astype(int))).fillna(0).astype(int)
    elif period == 'Y':
        df['Periods'] = (df['Data da Venda'].dt.year - 
                         df['CohortDate'].dt.year.fillna(0).astype(int)).fillna(0).astype(int)
    
    cohort_data = df.groupby(['CohortDate', 'ID do Cliente', 'Periods'])['Valor da Venda'].sum().reset_index()
    cohort_data['CumulativeRevenue'] = cohort_data.groupby(['CohortDate', 'ID do Cliente'])['Valor da Venda'].cumsum()
    
    avg_revenue = cohort_data.groupby(['CohortDate', 'Periods'])['CumulativeRevenue'].mean().reset_index()
    
    # Garantir que a receita cumulativa nunca diminua
    avg_revenue = avg_revenue.sort_values(['CohortDate', 'Periods'])
    avg_revenue['CumulativeRevenue'] = avg_revenue.groupby('CohortDate')['CumulativeRevenue'].cummax()
    
    return avg_revenue

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
    df['Data da Venda'] = pd.to_datetime(df['Data da Venda'], errors='coerce')
    df = df.dropna(subset=['Data da Venda'])
    
    # Opções de agregação
    agg_options = {
        "Mensal": "M",
        "Trimestral": "Q",
        "Anual": "Y"
    }

    # Seleção do nível de agregação (no sidebar para ser global)
    aggregation = st.sidebar.selectbox("Selecione o nível de agregação para toda a análise", list(agg_options.keys()))
    
    # Opção para escolher como calcular o Valor da Venda
    valor_venda_opcao = st.radio(
        "Como você quer definir o Valor da Venda?",
        ("Selecionar coluna", "Usar fórmula")
    )

    # No início do seu script, após as importações
    if 'formula' not in st.session_state:
        st.session_state.formula = ""
    if 'column_inputs' not in st.session_state:
        st.session_state.column_inputs = {}

    # Modifique a parte do cálculo do Valor da Venda assim:
    if valor_venda_opcao == "Selecionar coluna":
        value_column = st.selectbox("Selecione a coluna para Valor da Venda", df.columns)
        df['Valor da Venda'] = df[value_column]
        st.session_state.formula = ""
        st.session_state.column_inputs = {}
    else:
        st.subheader("Cálculo do Valor da Venda")
        value_columns = st.multiselect("Selecione as colunas para o cálculo do Valor da Venda", df.columns)
        column_inputs = {col: st.text_input(f"Alias para {col}", col) for col in value_columns}
        formula = st.text_input("Fórmula para o Valor da Venda (use os aliases e operadores +, -, *, /, e parênteses)", st.session_state.formula)
        
        if st.button("Aplicar Fórmula") or (st.session_state.formula and st.session_state.column_inputs):
            st.session_state.formula = formula
            st.session_state.column_inputs = column_inputs
            df = calculate_sale_value(df, formula, column_inputs)
            if df is not None:
                st.success("Fórmula aplicada com sucesso!")

    # Após a seleção do nível de agregação
    if st.session_state.formula and st.session_state.column_inputs:
        df = calculate_sale_value(df, st.session_state.formula, st.session_state.column_inputs)
        if df is None:
            st.error("Erro ao reaplicar a fórmula. Por favor, verifique e aplique novamente.")
            st.stop()

    if 'Valor da Venda' not in df.columns:
        st.error("A coluna 'Valor da Venda' não foi definida. Por favor, defina-a antes de continuar.")
        st.stop()

    # Filtro de data
    min_date = df['Data da Venda'].min().date()
    max_date = df['Data da Venda'].max().date()
    start_date, end_date = st.sidebar.date_input(
        "Intervalo de Datas",
        [min_date, max_date],
        min_value=min_date,
        max_value=max_date
    )
    
    # Aplicar filtros
    mask = (df['Data da Venda'].dt.date >= start_date) & (df['Data da Venda'].dt.date <= end_date)
    filtered_df = df.loc[mask]
    
    # Verificar vendas sem ID de cliente
    vendas_sem_id = filtered_df[filtered_df['ID do Cliente'].isnull() | (filtered_df['ID do Cliente'] == '')]
    receita_sem_id = vendas_sem_id['Valor da Venda'].sum()

    # Cálculos principais
    receita_total = filtered_df['Valor da Venda'].sum()
    clientes_unicos = filtered_df['ID do Cliente'].nunique()
    numero_total_vendas = len(filtered_df)

    # Cálculos por cliente (apenas para vendas com ID de cliente)
    df_com_id = filtered_df[filtered_df['ID do Cliente'].notna() & (filtered_df['ID do Cliente'] != '')]
    receita_por_cliente = df_com_id.groupby('ID do Cliente')['Valor da Venda'].sum()
    receita_media_cliente = receita_por_cliente.mean()
    receita_mediana_cliente = receita_por_cliente.median()

    # Ticket médio
    ticket_medio = receita_total / numero_total_vendas

    # Transações por cliente
    transacoes_por_cliente = df_com_id.groupby('ID do Cliente').size()
    numero_medio_transacoes = transacoes_por_cliente.mean()
    numero_mediano_transacoes = transacoes_por_cliente.median()

    # Exibição das métricas
    st.subheader("Métricas Principais")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Receita Total", f"R$ {format_br(receita_total)}")
        st.metric("Clientes Únicos", f"{clientes_unicos:n}")
        st.metric("Número Total de Vendas", f"{numero_total_vendas:n}")
    with col2:
        st.metric("Ticket Médio por Transação", f"R$ {format_br(ticket_medio)}")
        st.metric("Número Médio de Transações por Cliente", f"{format_br(numero_medio_transacoes)}")
        st.metric("Número Mediano de Transações por Cliente", f"{format_br(numero_mediano_transacoes)}")
    with col3:
        st.metric("Receita Média por Cliente", f"R$ {format_br(receita_media_cliente)}")
        st.metric("Receita Mediana por Cliente", f"R$ {format_br(receita_mediana_cliente)}")

    # Métricas de LTV
    st.subheader("Métricas de LTV")
    margem_contribuicao = st.slider("Margem de Contribuição (%)", 0, 100, 50)

    ltv_medio = receita_media_cliente * (margem_contribuicao / 100)
    ltv_mediano = receita_mediana_cliente * (margem_contribuicao / 100)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("LTV Médio por Cliente", f"R$ {format_br(ltv_medio)}")
    with col2:
        st.metric("LTV Mediano por Cliente", f"R$ {format_br(ltv_mediano)}")

    # Gráfico de vendas (novos vs recorrentes)
    st.subheader(f"Vendas: Novos vs Recorrentes ({aggregation})")
    
    filtered_df['FirstPurchase'] = filtered_df.groupby('ID do Cliente')['Data da Venda'].transform('min')
    filtered_df['CustomerType'] = np.where(filtered_df['Data da Venda'] == filtered_df['FirstPurchase'], 'Novo', 'Recorrente')

    sales_agg = filtered_df.set_index('Data da Venda').groupby([pd.Grouper(freq=agg_options[aggregation]), 'CustomerType'])['Valor da Venda'].sum().unstack(fill_value=0)

    fig = px.bar(sales_agg, 
                 x=sales_agg.index, 
                 y=['Novo', 'Recorrente'], 
                 title=f'Vendas por {aggregation} (Novos vs Recorrentes)',
                 labels={'value': 'Valor de Vendas', 'Data da Venda': 'Data'},
                 barmode='stack')

    st.plotly_chart(fig)

    # Análise de Coorte
    st.subheader("Análise de Coorte")
    cohort_df = calculate_cohorts(filtered_df, agg_options[aggregation])
    
    fig_cohort_heatmap = px.imshow(cohort_df, 
                                   text_auto='.0%', 
                                   aspect="auto", 
                                   color_continuous_scale='RdYlGn',
                                   zmin=0, 
                                   zmax=1)

    fig_cohort_heatmap.update_layout(
        title=f'Retenção de Coorte - Heatmap ({aggregation})',
        xaxis_title='Períodos',
        yaxis_title='Coorte',
        coloraxis_colorbar=dict(
            title='Taxa de Retenção',
            tickformat='.0%'
        )
    )

    fig_cohort_heatmap.update_traces(textfont_size=10)

    st.plotly_chart(fig_cohort_heatmap, use_container_width=True)
    
    # Gráfico de retenção de coorte baseado em linhas
    cohort_pivot = cohort_df.reset_index()
    cohort_pivot = cohort_pivot.melt(id_vars=['CohortDate'], var_name='Periods', value_name='Retention')
    cohort_pivot['Periods'] = cohort_pivot['Periods'].astype(int)

    fig_cohort_line = px.line(cohort_pivot, 
                              x='Periods', 
                              y='Retention', 
                              color='CohortDate', 
                              title=f'Retenção de Coorte ({aggregation})')

    fig_cohort_line.update_layout(
        xaxis_title='Períodos',
        yaxis_title='Taxa de Retenção',
        yaxis_tickformat='.0%'
    )

    st.plotly_chart(fig_cohort_line, use_container_width=True)

    # Gráfico de receita média cumulativa por cliente por coorte
    st.subheader("Receita Média Cumulativa por Cliente")

    avg_revenue = calculate_cumulative_revenue(filtered_df, agg_options[aggregation])

    if not avg_revenue.empty:
        fig_cumulative_revenue = px.line(avg_revenue, 
                                         x='Periods', 
                                         y='CumulativeRevenue', 
                                         color='CohortDate', 
                                         title=f'Receita Média Cumulativa por Cliente ({aggregation})')

        fig_cumulative_revenue.update_layout(
            xaxis_title='Períodos',
            yaxis_title='Receita Média Cumulativa (R$)',
            yaxis_tickformat=',.0f'
        )

        st.plotly_chart(fig_cumulative_revenue, use_container_width=True)
    else:
        st.warning("Não há dados suficientes para gerar o gráfico de Receita Média Cumulativa por Cliente.")

    # Treemap RFM interativo
    st.subheader("Segmentação RFM")

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
    fig_rfm = px.treemap(
        names=segment_counts.index,
        parents=[""] * len(segment_counts),
        values=segment_counts.values,
        title='Segmentação RFM'
    )

    # Adicionar informações de clientes e receita ao hover
    hover_data = []
    for segment in segment_counts.index:
        segment_df = rfm_segmented[rfm_segmented['Segment'] == segment]
        clients = ", ".join(segment_df.index.astype(str)[:5])  # Converter para string e mostrar apenas os primeiros 5 clientes
        total_revenue = segment_df['Monetary'].sum()
        hover_data.append(f"Clientes: {clients}...<br>Receita Total: R$ {format_br(total_revenue)}")

    fig_rfm.data[0].customdata = hover_data
    fig_rfm.data[0].hovertemplate = '%{label}<br>Quantidade: %{value}<br>%{customdata}'

    st.plotly_chart(fig_rfm, use_container_width=True, use_container_height=True)

    # Seleção interativa do segmento
    selected_segment = st.selectbox("Selecione um segmento para ver detalhes:", segment_counts.index)

    # Exibir detalhes do segmento selecionado
    if selected_segment:
        segment_df = rfm_segmented[rfm_segmented['Segment'] == selected_segment]
        
        st.subheader(f"Detalhes do Segmento: {selected_segment}")
        st.write(f"Número de Clientes: {len(segment_df)}")
        st.write(f"Receita Total: R$ {format_br(segment_df['Monetary'].sum())}")
        
        st.dataframe(segment_df[['R', 'F', 'M', 'Monetary']])
        
        # Opção de download
        csv = segment_df.to_csv(index=True)
        st.download_button(
            label="Download dados dos clientes deste segmento",
            data=csv,
            file_name=f"clientes_segmento_{selected_segment}.csv",
            mime="text/csv",
        )

    # Informações adicionais para debug
    st.subheader("Informações de Debug")
    st.write(f"Receita total: R$ {format_br(receita_total)}")
    st.write(f"Soma da receita por cliente (com ID): R$ {format_br(receita_por_cliente.sum())}")
    st.write(f"Receita de vendas sem ID de cliente: R$ {format_br(receita_sem_id)}")
    st.write(f"Número de vendas sem ID de cliente: {len(vendas_sem_id):n}")
    st.write(f"Diferença: R$ {format_br(receita_total - receita_por_cliente.sum() - receita_sem_id)}")

    # Alerta sobre vendas sem ID de cliente
    if receita_sem_id > 0:
        st.warning(f"Atenção: Existem R$ {format_br(receita_sem_id)} em vendas sem ID de cliente. Isso afeta o cálculo das métricas por cliente.")

else:
    st.info("Por favor, faça o upload de um arquivo CSV ou XLSX para começar a análise.")