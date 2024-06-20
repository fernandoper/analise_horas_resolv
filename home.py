import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from msal import ConfidentialClientApplication
import requests
import io
import openpyxl

# streamlit run home.py
# pip freeze > requirements.txt
# taskkill /F /IM python.exe


st.set_page_config(page_title='Pereira Advogados', page_icon='images/logopa.png', layout='wide')

# ====================================================================
# FUNÇÕES CONEXÃO SHAREPOINT
# ====================================================================

def obter_cliente_msal(client_id, tenant_id, client_secret):
    authority = f'https://login.microsoftonline.com/{tenant_id}'
    app = ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret
    )
    return app


def obter_token_acesso(app):
    token_response = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    return token_response.get('access_token', '')


def download_file_from_sharepoint(headers, file_id, site_id, drive_id):
    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/items/{file_id}/content"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return io.BytesIO(response.content)


# Autenticação usando MSAL
client_id = st.secrets["sharepoint"]["client_id"]
client_secret = st.secrets["sharepoint"]["client_secret"]
tenant_id = st.secrets["sharepoint"]["tenant_id"]

app = obter_cliente_msal(client_id, tenant_id, client_secret)
access_token = obter_token_acesso(app)

headers = {
    'Authorization': f'Bearer {access_token}',
    'Content-Type': 'application/json'
}

# Configurações do SharePoint
site_id = st.secrets["sharepoint"]["site_id"]
drive_id = st.secrets["sharepoint"]["drive_id"]
planilha_horas_id = st.secrets["sharepoint"]["planilha_horas_id"]
planilha_pagamentos_id = st.secrets["sharepoint"]["planilha_pagamentos_id"]

# Baixar arquivos
try:
    file_content_hours = download_file_from_sharepoint(headers, planilha_horas_id, site_id, drive_id)
    file_content_payments = download_file_from_sharepoint(headers, planilha_pagamentos_id, site_id, drive_id)
except requests.exceptions.HTTPError as e:
    st.error(f"Erro ao baixar arquivos: {e}")


# ====================================================================
# FUNÇÕES CONEXÃO SHAREPOINT
# ====================================================================

def check_credentials(username, password):
    correct_username = st.secrets["credentials"]["username"]
    correct_password = st.secrets["credentials"]["password"]
    return username == correct_username and password == correct_password


# Container para login
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

if not st.session_state['authenticated']:
    with st.sidebar:
        entered_username = st.text_input("Username")
        entered_password = st.text_input("Password", type="password")
        if st.button("Login"):
            if check_credentials(entered_username, entered_password):
                st.session_state['authenticated'] = True
                st.experimental_rerun()  # Re-executa o script para atualizar o estado do login
            else:
                st.error("Username or password is incorrect")
else:
    # Remova o container de login da barra lateral
    st.sidebar.empty()

if st.session_state['authenticated']:

    # Carregar dados
    dados_horas = pd.read_excel(file_content_hours, sheet_name='horas_resolv')
    dados_pagamentos = pd.read_excel(file_content_payments)

    # ====================================================================
    # CSS CONFIGS
    # ====================================================================
    st.markdown("""
    <style>
        .st-emotion-cache-1wivap2.e1i5pmia3 {
            font-size: 20px !important;  /* Ajuste o tamanho conforme necessário */
        }
    </style>
    """, unsafe_allow_html=True)


    # ====================================================================
    # FUNÇÕES
    # ====================================================================
    def reset_filters():
        st.session_state['area_selecionada'] = 'Todas'
        st.session_state['executante_selecionado'] = 'Todos'
        st.session_state['tipo_hora_selecionado'] = 'Todos'
        st.session_state['cliente_selecionado'] = []


    def wrap_text(text, width):
        """
        Função para quebrar o texto em várias linhas.
        """
        return '<br>'.join(text[i:i + width] for i in range(0, len(text), width))


    # ====================================================================
    # FUNÇÕES CRUZAMENTO TABELA HORAS E PAGAMENTOS
    # ====================================================================
    def process_data(horas_df, pagamentos_df):
        # Converte as colunas de data para o formato datetime
        horas_df['data'] = pd.to_datetime(horas_df['data'])
        pagamentos_df['data_pag'] = pd.to_datetime(pagamentos_df['data_pag'])

        # Agrupa os dados mensais somando as colunas especificadas
        horas_mensais = horas_df.resample('ME', on='data')['duracao', 'cobranca', 'custo'].sum().reset_index()
        pagamentos_mensais = pagamentos_df.resample('ME', on='data_pag')['valor_pag'].sum().reset_index()

        # Mescla os dados de horas e pagamentos com base nas datas
        merged_data = pd.merge(horas_mensais, pagamentos_mensais, left_on='data', right_on='data_pag', how='left')
        merged_data = merged_data.rename(columns={'duracao': 'Horas Trabalhadas', 'valor_pag': 'Valor Pago'})
        merged_data = merged_data.fillna(0)

        # Desloca o valor pago para o mês anterior para cálculos
        merged_data['Valor Pago Anterior'] = merged_data['Valor Pago'].shift(-1).fillna(0)

        # Calcula a diferença percentual entre o valor pago e a cobrança
        merged_data['Diferença % Pago/Cobrança'] = ((merged_data['Valor Pago Anterior'] - merged_data['cobranca']) /
                                                    merged_data['cobranca'].replace(0, 1)) * 100

        # Calcula a diferença percentual entre o valor pago e o custo
        merged_data['Diferença % Pago/Custo'] = ((merged_data['Valor Pago Anterior'] - merged_data['custo']) /
                                                 merged_data['custo'].replace(0, 1)) * 100

        # Calcula a margem de lucro bruta
        merged_data['Margem de Lucro Bruta'] = ((merged_data['Valor Pago Anterior'] - merged_data['custo']) /
                                                merged_data['Valor Pago Anterior'].replace(0, 1)) * 100

        return merged_data


    dados_processados = process_data(dados_horas, dados_pagamentos)


    # Relação entre Cobrança e Custo e Valor Pago
    def plot_hours_vs_payments(dataframe):
        fig = go.Figure()
        fig.add_trace(go.Bar(x=dataframe['data'], y=dataframe['Valor Pago'], name='Valor Pago', marker_color='#2ca02c',
                             text=[f"{y / 1000:.0f}k" for y in dataframe['Valor Pago']], textposition='outside'))
        fig.add_trace(go.Bar(x=dataframe['data'], y=dataframe['cobranca'], name='Cobrança', marker_color='#ff7f0e',
                             text=[f"{y / 1000:.0f}k" for y in dataframe['cobranca']], textposition='outside'))
        fig.add_trace(go.Bar(x=dataframe['data'], y=dataframe['custo'], name='Custo', marker_color='#1f77b4',
                             text=[f"{y / 1000:.0f}k" for y in dataframe['custo']], textposition='outside'))

        fig.update_layout(
            title={
                'text': "Comparação Mensal de Valores Pagos, Cobrança e Custo (R$)",
                'y': 1.0,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            title_font=dict(size=20),
            margin=dict(l=10, r=10, t=30, b=10),
            xaxis_title="Data",
            yaxis_title="Valores",
            barmode='group',
            height=600,
            width=1000
        )

        fig.update_yaxes(range=[0, dataframe[['cobranca', 'custo', 'Valor Pago']].max().max() * 1.2])
        return fig


    # Função para gráfico de diferença percentual pago/cobrança
    def plot_diff_paid_vs_billed(dataframe):
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dataframe['data'],
            y=dataframe['Diferença % Pago/Cobrança'],
            mode='lines+markers+text',
            name='Diferença % Pago/Cobrança',
            line=dict(color='#ff7f0e'),
            text=[f"{y:.2f}%" for y in dataframe['Diferença % Pago/Cobrança']],
            textposition='top center'
        ))
        fig.update_layout(
            title={
                'text': "Diferença Percentual Pago/Cobrança por Mês",
                'y': 0.95,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            yaxis_title="Diferença (%)",
            xaxis_title="Data",
            height=300,
            margin=dict(l=10, r=10, t=30, b=10),
            title_font=dict(size=20)
        )
        fig.update_yaxes(range=[-100, 100], zeroline=True, zerolinewidth=2, zerolinecolor='grey', automargin=True)
        return fig


    # Função para gráfico de diferença percentual pago/custo
    def plot_diff_paid_vs_cost(dataframe):
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dataframe['data'],
            y=dataframe['Diferença % Pago/Custo'],
            mode='lines+markers+text',
            name='Diferença % Pago/Custo',
            line=dict(color='#2ca02c'),
            text=[f"{y:.2f}%" for y in dataframe['Diferença % Pago/Custo']],
            textposition='top center'
        ))
        fig.update_layout(
            title={
                'text': "Diferença Percentual Pago/Custo por Mês",
                'y': 0.95,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            yaxis_title="Diferença (%)",
            xaxis_title="Data",
            height=300,
            margin=dict(l=10, r=10, t=30, b=10),
            title_font=dict(size=20)
        )
        fig.update_yaxes(range=[-100, 100], zeroline=True, zerolinewidth=2, zerolinecolor='grey', automargin=True)
        return fig


    # Função para gráfico de margem de lucro bruta
    def plot_gross_margin(dataframe):
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dataframe['data'],
            y=dataframe['Margem de Lucro Bruta'],
            mode='lines+markers+text',
            name='Margem de Lucro Bruta',
            line=dict(color='#1f77b4'),
            text=[f"{y:.2f}%" for y in dataframe['Margem de Lucro Bruta']],
            textposition='top center'
        ))
        fig.update_layout(
            title={
                'text': "Margem de Lucro Bruta por Mês",
                'y': 0.95,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            yaxis_title="Margem (%)",
            xaxis_title="Data",
            height=300,
            margin=dict(l=10, r=10, t=30, b=10),
            title_font=dict(size=20)
        )
        fig.update_yaxes(range=[-100, 100], zeroline=True, zerolinewidth=2, zerolinecolor='grey', automargin=True)
        return fig


    # Relação entre Cobrança e Custo
    def plot_cobranca_vs_custo(dataframe):
        fig = go.Figure()
        fig.add_trace(go.Bar(x=dataframe['data'], y=dataframe['cobranca'], name='Cobrança', marker_color='#ff7f0e',
                             text=[f"{y / 1000:.0f}k" for y in dataframe['cobranca']], textposition='outside'))
        fig.add_trace(go.Bar(x=dataframe['data'], y=dataframe['custo'], name='Custo', marker_color='#1f77b4',
                             text=[f"{y / 1000:.0f}k" for y in dataframe['custo']], textposition='outside'))

        fig.update_layout(
            title={
                'text': "Comparação Mensal de Cobrança e Custo (R$)",
                'y': 1.0,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            title_font=dict(size=20),
            margin=dict(l=10, r=10, t=30, b=10),
            xaxis_title="Data",
            yaxis_title="Valores",
            barmode='group',
            height=600,
            width=1000
        )

        fig.update_yaxes(range=[0, dataframe[['cobranca', 'custo']].max().max() * 1.2])
        return fig


    # ====================================================================
    # FUNÇÕES TABELA HORAS
    # ====================================================================

    # Horas por área
    def plot_hours_by_area(dataframe):
        dataframe['duracao'] = dataframe['duracao'].astype(float)
        area_hours = dataframe.groupby('área')['duracao'].sum().reset_index()
        area_hours = area_hours.sort_values('duracao', ascending=False).round()
        fig = px.bar(area_hours, x='área', y='duracao',
                     title='Horas Trabalhadas por Área',
                     labels={'duracao': 'Horas Trabalhadas', 'área': 'Área'},
                     color='duracao',
                     text='duracao',
                     color_continuous_scale=px.colors.sequential.Viridis)
        fig.update_traces(texttemplate='%{text}', textposition='outside')
        fig.update_layout(xaxis_title="Área",
                          yaxis_title="Horas Trabalhadas",
                          uniformtext_minsize=8,
                          uniformtext_mode='hide',
                          coloraxis_showscale=False)
        fig.update_yaxes(range=[0, area_hours['duracao'].max() * 1.2])
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
        fig.update_layout(
            autosize=True,
            title={
                'text': "Horas Trabalhadas por Área",
                'y': 1.0,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            title_font=dict(size=20)
        )
        return fig


    # Horas por executante
    def plot_hours_by_executante(dataframe):
        dataframe['duracao'] = dataframe['duracao'].astype(float)
        executante_hours = dataframe.groupby('executante')['duracao'].sum().reset_index()
        executante_hours['duracao'] = executante_hours['duracao'].round()  # Arredondar os valores
        executante_hours = executante_hours.sort_values('duracao', ascending=False).head(15)

        fig = px.bar(executante_hours, y='executante', x='duracao',
                     title='Horas Trabalhadas por Executante',
                     labels={'duracao': 'Horas Trabalhadas', 'executante': 'Executante'},
                     color='duracao',
                     orientation='h',
                     color_continuous_scale=px.colors.sequential.Viridis)

        fig.update_traces(texttemplate='%{x}', textposition='outside')
        fig.update_layout(xaxis_title="Horas Trabalhadas",
                          yaxis_title="Executante",
                          uniformtext_minsize=8,
                          uniformtext_mode='hide',
                          coloraxis_showscale=False)
        fig.update_xaxes(range=[0, executante_hours['duracao'].max() * 1.2])
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
        fig.update_layout(
            autosize=True,
            title={
                'text': "Horas Trabalhadas por Executante",
                'y': 1.0,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            title_font=dict(size=20)
        )
        fig.update_yaxes(autorange="reversed")

        return fig


    # Horas lançadas por dia - evolução
    def plot_hours_over_time(dataframe):
        dataframe['duracao'] = dataframe['duracao'].astype(float)
        dataframe['data'] = pd.to_datetime(dataframe['data'])
        date_hours = dataframe.resample('W-Mon', on='data')['duracao'].sum().reset_index().sort_values('data')
        date_hours['duracao'] = date_hours['duracao'].round()  # Arredondar os valores

        fig = px.line(date_hours, x='data', y='duracao',
                      title='Evolução das Horas Trabalhadas ao Longo do Tempo (Semanal)',
                      labels={'duracao': 'Horas Trabalhadas', 'data': 'Data'},
                      markers=True,
                      color_discrete_sequence=px.colors.sequential.Blugrn)

        for data_pt in date_hours.itertuples():
            fig.add_annotation(x=data_pt.data, y=data_pt.duracao,
                               text=f"{data_pt.duracao:.2f}",
                               showarrow=True,
                               arrowhead=1,
                               ax=0,
                               ay=-20)

        fig.update_layout(
            autosize=True,
            title={
                'text': "Evolução das Horas Trabalhadas ao Longo do Tempo (Semanal)",
                'y': 0.95,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'},
            title_font=dict(size=20),
            margin=dict(l=10, r=10, t=60, b=10)  # Ajusta a margem superior para mais espaço
        )

        return fig


    # Top horas por cliente
    def plot_hours_by_client(dataframe):
        dataframe['duracao'] = dataframe['duracao'].astype(float)
        client_hours = dataframe.groupby('cliente')['duracao'].sum().reset_index()
        client_hours['duracao'] = client_hours['duracao'].round()  # Arredondar os valores
        client_hours = client_hours.sort_values('duracao', ascending=False).head(10)

        fig = px.bar(client_hours, y='cliente', x='duracao',
                     title='Top 10 Clientes com Mais Horas Trabalhadas',
                     labels={'duracao': 'Horas Trabalhadas', 'cliente': 'Cliente'},
                     color='duracao',
                     orientation='h',
                     color_continuous_scale=px.colors.sequential.Viridis)

        fig.update_traces(texttemplate='%{x}', textposition='outside')
        fig.update_layout(xaxis_title="Horas Trabalhadas",
                          yaxis_title="Cliente",
                          uniformtext_minsize=8,
                          uniformtext_mode='hide',
                          coloraxis_showscale=False)
        fig.update_xaxes(range=[0, client_hours['duracao'].max() * 1.2])
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
        fig.update_layout(
            autosize=True,
            title={
                'text': "Top 10 Clientes com Mais Horas Trabalhadas",
                'y': 1.0,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            title_font=dict(size=20)
        )
        fig.update_yaxes(autorange="reversed")

        return fig


    # Tipos de hora trabalhadas
    def plot_hours_by_type(dataframe):
        dataframe['duracao'] = dataframe['duracao'].astype(float)
        tipo_service = dataframe.groupby('tipo_hora')['duracao'].sum().reset_index()
        tipo_service['duracao'] = tipo_service['duracao'].round()  # Arredondar os valores
        tipo_service = tipo_service.sort_values('duracao', ascending=False).head(8)

        fig = px.bar(
            tipo_service,
            y='tipo_hora',
            x='duracao',
            title='Hora Trabalhada por Tipo de Pasta',
            labels={'duracao': 'Horas Trabalhadas', 'tipo_hora': 'Tipo de Serviço'},
            color='duracao',
            orientation='h',
            color_continuous_scale=px.colors.sequential.Rainbow
        )

        fig.update_traces(texttemplate='%{x} horas', textposition='outside')
        fig.update_layout(
            xaxis_title="Horas Trabalhadas",
            yaxis_title="Tipo de Serviço",
            uniformtext_minsize=8,
            uniformtext_mode='hide',
            coloraxis_showscale=False,
            autosize=True,
            title={
                'text': "Hora Trabalhada por Tipo de Pasta",
                'y': 0.9,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            title_font=dict(size=20),
            margin=dict(l=10, r=10, t=30, b=10)
        )

        fig.update_xaxes(range=[0, tipo_service['duracao'].max() * 1.2])
        fig.update_yaxes(categoryorder='total descending')

        return fig


    # Horas / Cobrança / Custo por Tipo de Serviço
    def plot_hours_by_service_type(dataframe):
        dataframe['duracao'] = dataframe['duracao'].astype(float)
        dataframe['cobranca'] = dataframe['cobranca'].astype(float)
        dataframe['custo'] = dataframe['custo'].astype(float)

        # Agrupar por tipo de serviço para obter a soma das horas
        tipo_service_data = dataframe.groupby('tipo').agg({
            'duracao': 'sum',
            'cobranca': 'sum',
            'custo': 'sum'
        }).reset_index()

        # Calcular os percentuais
        total_horas = tipo_service_data['duracao'].sum()
        total_cobranca = tipo_service_data['cobranca'].sum()
        total_custo = tipo_service_data['custo'].sum()

        tipo_service_data['percent_horas'] = (tipo_service_data['duracao'] / total_horas) * 100
        tipo_service_data['percent_cobranca'] = (tipo_service_data['cobranca'] / total_cobranca) * 100
        tipo_service_data['percent_custo'] = (tipo_service_data['custo'] / total_custo) * 100

        # Ordenar os tipos de serviço pela soma das horas trabalhadas
        tipo_service_data = tipo_service_data.sort_values('duracao', ascending=False).head(10)

        # Criar a coluna de texto combinada
        tipo_service_data['text'] = (
                tipo_service_data['duracao'].round(2).astype(str) + ' horas - ' +
                (tipo_service_data['cobranca'] / 1000).round(2).astype(str) + 'k (' + tipo_service_data[
                    'percent_cobranca'].round(2).astype(str) + '%) - ' +
                (tipo_service_data['custo'] / 1000).round(2).astype(str) + 'k (' + tipo_service_data[
                    'percent_custo'].round(
            2).astype(str) + '%)'
        )

        fig = go.Figure()

        # Adicionar a barra única com a informação combinada
        fig.add_trace(go.Bar(
            y=tipo_service_data['tipo'],
            x=tipo_service_data['duracao'],
            name='Informações Combinadas',
            orientation='h',
            marker=dict(color=tipo_service_data['duracao'], colorscale='Rainbow'),
            text=tipo_service_data['text'],
            textposition='outside'
        ))

        fig.update_layout(
            title={
                'text': "Horas / Cobrança / Custo por Tipo de Serviço",
                'y': 1.0,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            title_font=dict(size=20),
            xaxis_title="Valores",
            yaxis_title="Tipo de Serviço",
            barmode='group',
            height=900,
            margin=dict(l=10, r=50, t=30, b=10)
        )

        max_val = tipo_service_data['duracao'].max()
        tickvals = list(range(0, int(max_val) + 100, 100))

        fig.update_xaxes(tickvals=tickvals, range=[0, max_val * 2])
        fig.update_yaxes(categoryorder='total ascending')
        fig.update_layout(
            yaxis=dict(
                tickfont=dict(size=12)
            )
        )

        return fig


    # Média de Horas / Qtidade de Pasta por Tipo de Serviço
    def plot_avg_hours_per_service_by_folder(dataframe):
        dataframe['duracao'] = dataframe['duracao'].astype(float)

        # Agrupar por tipo de serviço e pasta para obter a soma das horas por pasta e serviço
        service_folder_hours = dataframe.groupby(['tipo', 'vinculo_processo_servico'])['duracao'].sum().reset_index()

        # Agrupar novamente por tipo de serviço para obter a soma total das horas e a quantidade de pastas únicas
        avg_hours_per_service = service_folder_hours.groupby('tipo').agg({
            'duracao': 'sum',
            'vinculo_processo_servico': pd.Series.nunique
        }).reset_index()

        # Calcular a média das horas por pasta para cada tipo de serviço
        avg_hours_per_service['avg_hours'] = avg_hours_per_service['duracao'] / avg_hours_per_service[
            'vinculo_processo_servico']

        # Calcular o percentual de pastas do total
        total_pastas = service_folder_hours['vinculo_processo_servico'].nunique()
        avg_hours_per_service['percent_pastas'] = (avg_hours_per_service[
                                                       'vinculo_processo_servico'] / total_pastas) * 100

        # Ordenar em ordem decrescente pela quantidade de pastas
        avg_hours_per_service = avg_hours_per_service.sort_values(by='vinculo_processo_servico', ascending=False).head(
            10)

        # Quebrar o texto dos tipos de serviço
        avg_hours_per_service['tipo'] = avg_hours_per_service['tipo'].apply(lambda x: wrap_text(x, 30))

        # Criar a coluna de texto combinada
        avg_hours_per_service['text'] = avg_hours_per_service['avg_hours'].round(2).astype(str) + ' horas - ' + \
                                        avg_hours_per_service['vinculo_processo_servico'].astype(str) + ' pastas (' + \
                                        avg_hours_per_service['percent_pastas'].round(2).astype(str) + '%)'

        # Criar gráfico de barras horizontais com a média de horas por pasta
        fig = go.Figure()

        # Adicionar a barra com a informação combinada
        fig.add_trace(go.Bar(
            y=avg_hours_per_service['tipo'],
            x=avg_hours_per_service['avg_hours'],
            name='Média de Horas por Pasta',
            orientation='h',
            marker=dict(color=avg_hours_per_service['avg_hours'], colorscale='Rainbow'),  # Aplicar cores
            text=avg_hours_per_service['text'],
            textposition='outside'
        ))

        fig.update_layout(
            title={
                'text': "Média de Horas / Qtidade de Pasta por Tipo de Serviço",
                'y': 1.0,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            title_font=dict(size=20),
            xaxis_title="Valores",
            yaxis_title="Tipo de Serviço",
            barmode='group',
            height=900,  # Altura do gráfico - importante para dados grandes
            margin=dict(l=10, r=50, t=30, b=10)  # Ajuste a margem direita para evitar sobreposição
        )

        max_val = avg_hours_per_service['avg_hours'].max()
        tickvals = list(range(0, int(max_val) + 1, 1))

        fig.update_xaxes(tickvals=tickvals, range=[0, max_val * 1.35])  # Faz com que a barra não invada as legendas
        fig.update_yaxes(categoryorder='total ascending')
        fig.update_layout(
            yaxis=dict(
                tickfont=dict(size=12)
            )
        )

        return fig


    # ====================================================================
    # SIDEBAR LOGO
    # ====================================================================

    image_path = 'images/logopa.png'
    st.sidebar.image(image_path, use_column_width=True)

    # ====================================================================
    # SIDEBAR TITLES
    # ====================================================================

    st.sidebar.markdown("""
        <div style="text-align: center; font-weight: bold; font-size: 18px">
            Pereira Advogados
        </div>
    """, unsafe_allow_html=True)

    # Espaço extra antes do botão
    st.sidebar.markdown('<br>', unsafe_allow_html=True)

    # ====================================================================
    # SIDEBAR FILTERS
    # ====================================================================

    st.sidebar.header('Filtros')

    # ====================================================================
    # SLIDER DATE FILTER
    # ====================================================================

    # Define the min and max dates if not already defined
    min_date = dados_processados['data'].min()
    max_date = dados_processados['data'].max()

    # Filtro de data com slider
    selected_date_range = st.sidebar.slider(
        "Selecione o intervalo de datas:",
        value=(min_date.to_pydatetime(),
               max_date.to_pydatetime()),
        format='MM/YYYY'
    )

    # Convertendo as datas selecionadas para datetime, se necessário
    start_date, end_date = selected_date_range
    if not isinstance(start_date, pd.Timestamp):
        start_date = pd.to_datetime(start_date)
    if not isinstance(end_date, pd.Timestamp):
        end_date = pd.to_datetime(end_date)

    # ====================================================================
    # SLIDER FILTER
    # ====================================================================

    # Verifique se os estados dos filtros já estão definidos, caso contrário, inicialize-os
    if 'area_selecionada' not in st.session_state:
        st.session_state['area_selecionada'] = 'Todas'
    if 'executante_selecionado' not in st.session_state:
        st.session_state['executante_selecionado'] = 'Todos'
    if 'tipo_hora_selecionado' not in st.session_state:
        st.session_state['tipo_hora_selecionado'] = 'Todos'
    if 'cliente_selecionado' not in st.session_state:
        st.session_state['cliente_selecionado'] = []

    # Botão para resetar seleções
    if st.sidebar.button('Resetar Seleção'):
        reset_filters()
        st.experimental_rerun()

    # Sidebar com filtros
    st.sidebar.header('Filtros')

    # Filtro por área
    area_selecionada = st.sidebar.selectbox(
        'Selecione uma Área:',
        options=['Todas'] + sorted(dados_horas['área'].unique()),
        index=0,
        key='area_selecionada'
    )

    # Atualizar a lista de executantes com base na área selecionada
    if area_selecionada != 'Todas':
        executantes_area = sorted(dados_horas[dados_horas['área'] == area_selecionada]['executante'].unique())
    else:
        executantes_area = sorted(dados_horas['executante'].unique())

    # Filtro por executante
    executante_selecionado = st.sidebar.selectbox(
        'Selecione um Executante:',
        options=['Todos'] + executantes_area,
        index=0,
        key='executante_selecionado'
    )

    # Filtro por tipo de hora
    tipo_hora_selecionado = st.sidebar.selectbox(
        'Selecione o Tipo de Hora:',
        options=['Todos'] + sorted(dados_horas['tipo_hora'].unique()),
        index=0,
        key='tipo_hora_selecionado'
    )

    # Filtro por cliente com campo de pesquisa
    cliente_selecionado = st.sidebar.multiselect(
        'Selecione um Cliente:',
        options=sorted(dados_horas['cliente'].unique()),
        default=st.session_state['cliente_selecionado']
    )

    # Filtrar os dados de horas com base na data e nos filtros selecionados
    dados_filtrados = dados_horas[(dados_horas['data'] >= start_date) & (dados_horas['data'] <= end_date)].copy()

    if area_selecionada != 'Todas':
        dados_filtrados = dados_filtrados.loc[dados_filtrados['área'] == area_selecionada]
    if executante_selecionado != 'Todos':
        dados_filtrados = dados_filtrados.loc[dados_filtrados['executante'] == executante_selecionado]
    if tipo_hora_selecionado != 'Todos':
        dados_filtrados = dados_filtrados.loc[dados_filtrados['tipo_hora'] == tipo_hora_selecionado]
    if cliente_selecionado:
        dados_filtrados = dados_filtrados.loc[dados_filtrados['cliente'].isin(cliente_selecionado)]

    dados_filtrados['vinculo_processo_servico'] = dados_filtrados['vinculo_processo_servico'].astype(str)

    # Filtrar os dados processados com base na data selecionada
    dados_filtrados_processados = dados_processados[(dados_processados['data'] >= start_date) &
                                                    (dados_processados['data'] <= end_date)]

    # ====================================================================
    # PAGE CONTENT
    # ====================================================================

    # Título da aplicação
    st.markdown("""
        <h1 style="font-size:40px;">Dashboard de Horas Trabalhadas</h1>
        """, unsafe_allow_html=True)

    # Primeira linha de métricas
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total de Horas", f"{dados_filtrados['duracao'].sum():.2f} horas")
    with col2:
        st.metric("Total de Cobrança", f"R$ {dados_filtrados['cobranca'].sum():,.2f}")
    with col3:
        st.metric("Total de Custo", f"R$ {dados_filtrados['custo'].sum():,.2f}")

    # Segunda linha de métricas
    # Agrupando por 'tipo_hora' e somando as horas
    tipo_hora_agrupado = dados_filtrados.groupby('tipo_hora')['duracao'].sum()

    # Extraindo as métricas para cada tipo de hora
    metricas_tipo_hora = {
        'Horas Serviço': tipo_hora_agrupado.get('Serviço', 0),
        'Horas Interno': tipo_hora_agrupado.get('Interno', 0),
        'Horas Processo': tipo_hora_agrupado.get('Processo', 0)
    }

    col4, col5, col6 = st.columns(3)
    with col4:
        st.metric("Total Horas Serviço", f"{metricas_tipo_hora['Horas Serviço']:.2f} horas")
    with col5:
        st.metric("Total Horas Interno", f"{metricas_tipo_hora['Horas Interno']:.2f} horas")
    with col6:
        st.metric("Total Horas Processo", f"{metricas_tipo_hora['Horas Processo']:.2f} horas")

    st.text("")
    st.text("")

    # Gráficos
    dados_processados = process_data(dados_horas, dados_pagamentos)

    st.plotly_chart(plot_hours_vs_payments(dados_filtrados_processados))
    st.text("")
    st.plotly_chart(plot_diff_paid_vs_billed(dados_filtrados_processados))
    st.text("")
    st.plotly_chart(plot_diff_paid_vs_cost(dados_filtrados_processados))
    st.text("")
    st.plotly_chart(plot_gross_margin(dados_filtrados_processados))
    st.text("")
    st.plotly_chart(plot_cobranca_vs_custo(dados_filtrados_processados))
    st.text("")
    st.plotly_chart(plot_hours_by_area(dados_filtrados))
    st.text("")
    st.plotly_chart(plot_hours_by_executante(dados_filtrados))
    st.text("")
    st.plotly_chart(plot_hours_over_time(dados_filtrados))
    st.text("")
    st.plotly_chart(plot_hours_by_client(dados_filtrados))
    st.text("")
    st.plotly_chart(plot_hours_by_type(dados_filtrados))
    st.text("")
    st.plotly_chart(plot_hours_by_service_type(dados_filtrados))
    st.text("")
    st.plotly_chart(plot_avg_hours_per_service_by_folder(dados_filtrados))
    st.text("")

    # Título do dataframe
    st.markdown("""
        <h1 style="font-size:20px; text-align: center;">Descrição das Horas Trabalhadas</h1>
        """, unsafe_allow_html=True)

    # Exibir dados filtrados
    st.dataframe(dados_filtrados)

else:
    st.info("Please log in to view the content.")
