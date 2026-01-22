
RELATÓRIO DE IMPLEMENTAÇÃO DE SERVIÇOS AWS

Data: [21/02/2026]  
Empresa: Abstergo Industries  
Responsável: Vinicius Carneiro Souza e Silva 

---

Introdução:
Este relatório apresenta o processo de implementação de ferramentas na empresa Abstergo Industries, realizado por Vinicius Carneiro Souza e Silva.  
O objetivo do projeto foi selecionar e implementar 4 serviços da AWS, visando uma maior integração entre os sistemas de infraestrutura, agilizando toda a cadeia de processos e principalmente, com a redução de custos operacionais e a mitigação de qualquer gargalo existente na operação.

---

Descrição do Projeto
O projeto foi dividido em 4 etapas, onde cada etapa estará sendo descrita qual é o foco de cada ferramenta e os beneficios esperados em suas aplicações:

Etapa 1 - Infraestrutura e Hospedagem
- Nome das ferramentas: Amazon EC2 (Elastic Compute Cloud) e Amazon RDS (Relational Database Service)
- Foco das ferramentas: O Amazon EC2 tem como foco a hospedagem de servidores virtuais, que podem ser escaláveis a media que seja    preciso mais espaço de servidor. O RDS tem como foco a criação de um bancon de dados relacional gerenciavel. 
- Descrição do caso de uso: O EC2 será responsavel por fazer a hospedagem do site que irá ser construido, onde o EC2 permite o controle total de todos os recursos que serão aplicados no site. Os principais beneficios do EC2 é a escalabilidade sob demanda, onde poderemos aumentar ou diminuir a capacidade do servidor conforme tráfego. A cobrança é feita apenas em cima do que foi usado e Alta disponibilidade (Projetado para funcionar mesmo com a ocorrencia de falahs) e facilidade de integração com outros serviços oferecidos pela AWS. O RDS será onde se hospeda o banco de dados na nuvem, nele podem armazenar os principais dados da empresa, como clientes, os pedidos e o estoque de sua empresa. Seus principais benefícios, o backup automatico e alta disponibilidade (Projetado para funcionar mesmo com a ocorrencia de falahs), baixo esforço de manuntenção, opis a aws será responsavel por gerenciar as atualizações e pela segurança, podemos escalar tanto de forma vertical como horinzontal.

Etapa 2 - Armazenamento e Segurança
- Nome das ferramentas: Amazon S3 (Simple Storage Service) e AWS IAM (Identity and Access Management)
- Foco das ferramentas:Amazon S3 tem como foco o armazenamento de arquivos tipo objetos, que seriam relátorios e arquivos da empresa e o AWS IAM tem como seu principal foco o controle de acesso e a segurança dos dados que precisamos guardar.
- Descrição do caso de uso: Com o S3, criamos os buckts, onde podemos colocar os arquivos da empresa, no S3, usando o IAM, podemos configurar as politicas de acesso, temos controle das versões dos arquvios, podemos habilitar criptografia (AES -256 ou KMS) para proteção de dados sensiveis e com a intergração com o CloudFront, acelerar o envio dos arquivos, os principais benefícios do S3: Alta durabilidade, seu baixo custo e escalabilidade ilimitada e como citado já, a integração com o CDN (cloudfront) da AWS. O IAM, podemos criar usuarios ou grupo de usuarios com permissões de acesso especificas, podemos definir limites de acesso nos sitemas, para que sejam acessados apenas recursos necessários a operação, podemos aplicar recurosos de autenticação, recurosos de privilegios, onde podemos aplicar o principio do menor privilégio, onde garantimos a permissão apenas a recursos necessarios e monitorar os acessos e a produção de relatórios para auditorias. Seus principais beneficios: Politicas granulares, suporte a autenticação muiltifator e principalmente conformidade com a LGPD.

Etapa 3 - Escalabilidade, Performance e Custos
- Nome das ferramentas: Amazon CloudFront e AWS Lambda
- Foco das ferramentas: O CloundFront tem como foco a distribuição de conteúdo via CDN e o AWS Lambda fornece serviço de computação serverless para aplicações específicas.  
- Descrição do caso de uso: o CloudFront tem como principal aplicação a entrega de conteudo e arquivos com baixa latência, onde com isso podemos melhorar a resposta ao acesso dos usuarios ao nosso site, com isso reduzindo a carga nos servidores EC2, com ele ativamos o HTTPS, com isso, garantir a segurança dos dados entregues e principalmente, com o CloudFront tempos uma plataforma segura e confiavel entregue ao nosso usuário. O Lambda será usado para, processar os pedios, enviar notificações, tanto email como sms aos clientes. integração com API externas, no caso o sistema de pagamentos, podemos programar gatilhos para nos mostrar alterações no S3, eventos nos bancos de dados RDS, configurar as permissões via IAM para o acesso apenas recursos necessarios. Seus principais beneficios são redução de custos, alta escalabilidade automática e facil integração com outros serviços AWS

Etapa 4 – Monitoramento e Otimização
- Nome da ferramenta: CloudWatch 
- Foco da ferramenta: Monitoramento e o acompanhamento de metricas.
- Descrição do caso de uso: Com essa ferramenta, conseguimos configurar metricas de monitoramento, criar dashboards de acompanhamento em tempo real do que precisamos acompanhar, definir alarmes de segurança para recursos essênciais, podemos integrar com o Auto Scaling para ajuste de capacidade de forma automatica, conforme a demanda e principalmente, a geração de relatório para otimização de custos e analise de desempenho. Os principais benefícios, detecção rápidas dos problemas, geração de relatórios e integração com sistemas de automação. 
---

Conclusão
A implementação das ferramentas na empresa **Abstergo Industries** tem como objetivo escalar o crescimento de forma sustetavel, onde conseguiremos agilizar a resolução de problemas, melhorar a integração dos diversos departamentos da empresa, melhorar nosso atendimento ao publico e principamente a redução de custos operacionais, com isso melhorando a competividade da empresa no mercado.  
Recomendo a continuidade do uso das ferramentas AWS implemnetadas e a busca por atualizações ou novas tecnologias que possam melhorar cada vez mais os processos internos da empresa.

---

Anexos

Documentos oficiais da amazon sobre cada serviço:

- https://docs.aws.amazon.com/pt_br/ec2/?id=docs_gateway
- https://docs.aws.amazon.com/pt_br/rds/
- https://docs.aws.amazon.com/pt_br/s3/
- https://docs.aws.amazon.com/pt_br/iam/
- https://docs.aws.amazon.com/cloudfront/
- https://docs.aws.amazon.com/lambda/
- https://docs.aws.amazon.com/pt_br/cloudwatch/?id=docs_gateway

Nos acessos, serão encontrados:

Guias do usuário.
Referências de API.
PDFs para download.
Melhores práticas e exemplos.

---

Responsável pelo Projeto:

Vinicius Carneiro Souza e Silva
``
