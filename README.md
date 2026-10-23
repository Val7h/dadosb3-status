# Monitor externo do Dados B3

Este monitor olha o site **de fora do Render**. Se o site cair, o GitHub manda um e-mail. Ele também publica uma página de status em português e inglês.

Esta pasta está pronta, mas **nada foi ligado ainda**. Não existe repositório, não existe conta nova, nada foi publicado. Os passos abaixo são os que o dono faz, uma vez.

## O que ele confere (a cada 5 minutos)

| Endereço | O que precisa dar certo |
|---|---|
| `https://dadosb3.com/saude` | resposta 200, JSON válido, `build.estado` igual a `ok`, e `cobertura_de_preco.dias_desde_o_ultimo_pregao` no máximo 6 |
| `/` , `/acoes/PETR4` , `/fiis/mxrf11` , `/sitemap.xml` , `/mcp` | resposta 200 |

Cada endereço espera no máximo 20 segundos e tenta 2 vezes antes de dar falha. Se falhar, o job fica vermelho (o GitHub avisa por e-mail) e uma linha entra em `status/historico.csv`.

O limite de 6 dias do `/saude` é o mesmo que o site usa para acender o alarme (cobre fim de semana e feriado). Para mudar, edite `LIMITE_DIAS_SEM_PREGAO` em `.github/workflows/monitor.yml`.

## Passos do dono (uma vez)

1. No GitHub, crie um repositório novo, por exemplo `dadosb3-status`. Pode ser **privado** ou **público**.
   - Privado: o histórico e o código ficam só com você. A página de status (GitHub Pages) em repositório privado exige plano pago do GitHub. No plano grátis, a página só funciona se o repositório for público.
   - Público: de graça, e qualquer pessoa vê o histórico de quedas. Isso é o normal em páginas de status.
2. Envie o conteúdo desta pasta para o repositório (ramo `main`).
3. Em **Settings → Pages**, em "Build and deployment", escolha **Deploy from a branch**, ramo `main`, pasta `/docs`. Salve. O endereço da página aparece ali.
4. Em **Settings → Actions → General → Workflow permissions**, marque **Read and write permissions**. Sem isso o monitor não consegue guardar o histórico.
5. Em **Actions**, abra "Monitor externo do Dados B3" e clique em **Run workflow** para testar. Deve ficar verde.
6. Confira o e-mail de aviso:
   - Em **github.com → Settings → Notifications → Actions**, deixe ligado "Send notifications for failed workflows only" (e-mail marcado).
   - O aviso vai para a pessoa que **editou por último** o agendamento (`cron`) do arquivo `monitor.yml`. Faça essa edição com a sua conta.
   - Para ver o aviso funcionando, troque por um instante `https://dadosb3.com` por um endereço que não existe, rode o teste e volte atrás.
7. (Opcional) Crie `status/desde.txt` com a data em que o monitor foi ligado, no formato `2026-10-23`. Assim a disponibilidade de 30 dias não conta o tempo em que ainda não havia medição.

## Como funciona

- `verificar.py` faz as verificações e só escreve no histórico quando algo falha.
- `gerar_pagina.py` lê `status/historico.csv` e escreve `docs/index.html`: estado atual, disponibilidade em 24 h, 7 dias e 30 dias, e os últimos 20 incidentes. Sem JavaScript e sem fonte externa.
- O workflow guarda o histórico e a página no próprio repositório. A página só é regravada quando muda, ou ao menos uma vez por hora.
- Falhas seguidas da mesma verificação (até 12 minutos entre elas) viram um incidente só.

## Testar no seu computador (opcional)

```
python teste_local.py
python gerar_pagina.py --historico exemplo/historico_exemplo.csv --saida exemplo/index_exemplo.html
```

A pasta `exemplo/` serve só para teste; pode apagar. Não há segredo nem chave em nenhum arquivo. O monitor usa só endereços públicos.

## Limites que vale saber

- O agendamento do GitHub pode atrasar alguns minutos, e em repositório sem nenhuma atividade por 60 dias o GitHub pode pausar o agendamento. Como o monitor guarda o histórico no repositório quando algo muda, isso é raro; se acontecer, o GitHub avisa por e-mail e basta reativar em **Actions**.
- O monitor vê o que um visitante vê. Ele não sabe a causa; para isso há o `/admin/stats` do site (bloco `erros_5xx_por_hora`).
