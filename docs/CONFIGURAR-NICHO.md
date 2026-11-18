# Configurar o nicho de uma empresa

O **nicho** é o que faz o ProspectAI achar o lead certo para cada cliente. O
motor de busca é o mesmo para todo mundo; o nicho diz **o que procurar, como
dar nota, o que oferecer e com quem falar**.

Onde editar: **Empresas → Configurar → Nicho**. Use **Conferir** antes de
**Salvar**: ele aponta o erro em português (ex.: "Informe ao menos uma
palavra-chave"). O que você salva vale **a partir do próximo lote**.

> O texto usa o formato YAML: cada nível é recuado com 2 espaços, listas
> começam com `- ` e comentários começam com `#`. Se errar a indentação, o
> Conferir avisa a linha.

## Regra de casamento das palavras (vale para o arquivo todo)

- Acento e maiúscula não importam: `refeição` = `Refeicao`.
- **Frase** (com espaço) casa em qualquer lugar do texto: `cozinha industrial`.
- **Palavra única** casa só inteira: `bar` NÃO casa em `barato`.
- Palavra terminada em `*` casa pelo começo: `restaurant*` casa
  `restaurante` e `restaurantes`.

## Os blocos, um por um

### `nome` e `descricao`
Só para você se orientar (aparecem na lista de empresas e na tela do cliente).

### `busca` — onde e como procurar
| Campo | Para que serve | Dica |
|---|---|---|
| `palavras_chave` | Cada item vira uma busca na web | Escreva como o **cliente do seu cliente** se descreve no site dele |
| `buscas_premium` | Buscas do comprador "certo"; ~40% de cada lote sai daqui | Poucas e bem específicas |
| `modificadores` / `formas` | Variações combinadas com as palavras-chave | Deixe `""` na lista para às vezes não variar |
| `regioes` | Cidades/estados que entram nas buscas | Repita um item para dar mais peso |
| `ruido` | Pedaços de domínio/título que NÃO são lead (portais do setor, concorrentes) | Ex.: `guiadosetor` |
| `fornecedores` | Frases de quem VENDE para o mesmo comprador | Ex.: `fabricante de equipamentos` |
| `paginas_operacao` | Pedaços de link das páginas que descrevem a operação do lead | Ex.: `cardapio`, `unidades` |
| `titulos_de_servico` | Títulos que descrevem serviço, não o nome da empresa | Ex.: `buffet para` |
| `base_curada` | Domínios que você já sabe que servem (completa o lote) | Um por item: `empresa.com.br` |

### `pontuacao` — a nota de 0 a 100
- `hot` e `warm`: cortes. Nota ≥ `hot` = HOT; ≥ `warm` = WARM; abaixo disso o
  lead **nem é entregue** (preferimos entregar menos e melhor).
- `necessidades`: evidências de que a empresa **precisa** do que o cliente vende
  (`termo: peso`). Com `exige_sinal_de_necessidade: true`, sem nenhum desses o
  lead é COLD mesmo que o setor bata.
- `segmentos` e `tipos_empresa`: o tipo de negócio e a posição na cadeia.
- `concorrentes`: peso **negativo** para quem já vende a mesma coisa.
- Pesos entre -100 e 100. Comece com 5–15 e ajuste olhando os lotes.

### `solucoes` — o catálogo do cliente
Cada item aparece na coluna **Soluções** quando o site do lead mostra um dos
`sinais`.
- `nome`: como sai na planilha e no e-mail (`{solucoes}`).
- `curto`: como sai na tela (cabe na tabela).
- `sinais`: palavras de **operação** que indicam a necessidade (o site do lead
  quase nunca cita o nome do produto).
- `decisor`: cargo sugerido para abordar quem precisa desta solução.
- `oculta_se`: se alguma destas outras soluções já apareceu, esta some (um item
  que já vem incluído em outro).

### `decisores`
- `padrao`: cargo sugerido quando o site não mostra ninguém.
- `cargos`: cargos do nicho com `termo`, `rotulo` e `prioridade` (1–99). Os
  genéricos (presidente, diretor, gerente, compras…) já vêm no motor.

### `porte` — tamanho do lead
- `ativo: true` liga a leitura do número que a empresa publica.
- `unidades`: palavras que vêm **depois** do número (`40 lojas`).
- `contexto`: palavras que vêm **antes** (`rede de 40`).
- `rotulo`: como aparece na planilha (`40 unidades`).
- `media_a_partir_de` / `grande_a_partir_de`: cortes de Média/Grande.
- `qualifica_a_partir_de`: com N+ declarados o lead entra mesmo com nota baixa.
  **Deixe 0** até conhecer o nicho: número solto em site engana.
- Sem número publicado, o porte vem do capital social na Receita (qualquer nicho).

### `email`
- `palavras_operacao`: caixas que caem na operação do lead (`cozinha@`).
- `nao_e_pessoa`: palavras que nunca são nome de gente num e-mail do nicho.

## Como calibrar (o caminho que funciona)

1. Comece pelo exemplo e troque `palavras_chave`, `solucoes` e `necessidades`.
2. Gere um lote pequeno (10–20) na empresa.
3. Olhe os leads: o que entrou e não devia vira `ruido`/`concorrentes`; o que
   ficou de fora mas era bom vira `necessidades` com mais peso.
4. Repita. Dois ou três lotes costumam bastar.
