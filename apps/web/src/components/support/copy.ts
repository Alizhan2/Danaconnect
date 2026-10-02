export type SupportLocale = 'ru' | 'kk' | 'en';
const phrases = {
  title: ['Поддержка', 'Қолдау', 'Support'],
  description: ['Ваши обращения и ответы команды платформы.', 'Өтініштеріңіз және платформа тобының жауаптары.', 'Your requests and replies from the platform team.'],
  private: ['Переписка доступна вам и администраторам поддержки. Не отправляйте пароли, коды входа или ключи.', 'Хат алмасуды сіз және қолдау әкімшілері көре алады. Құпиясөздерді, кіру кодтарын немесе кілттерді жібермеңіз.', 'This conversation is available to you and support administrators. Do not send passwords, sign-in codes or keys.'],
  create: ['Новое обращение', 'Жаңа өтініш', 'New request'],
  subject: ['Тип обращения', 'Өтініш түрі', 'Request type'],
  support: ['Общий вопрос', 'Жалпы сұрақ', 'General question'],
  project: ['Вопрос о проекте', 'Жоба туралы сұрақ', 'Project issue'],
  mentor: ['Вопрос о менторе', 'Ментор туралы сұрақ', 'Mentor issue'],
  message: ['Вопрос о сообщении', 'Хабарлама туралы сұрақ', 'Message issue'],
  booking: ['Вопрос о встрече', 'Кездесу туралы сұрақ', 'Meeting issue'],
  context: ['Обращение будет связано с выбранным объектом. Общий вопрос можно отправить без завершения анкеты; для обращения об объекте нужен допущенный аккаунт.', 'Өтініш таңдалған нысанмен байланысады. Жалпы сұрақты сауалнама аяқталмай-ақ жіберуге болады; нысан туралы өтініш үшін мақұлданған есептік жазба қажет.', 'This request will refer to the selected item. You can ask a general question before completing your profile; an item-specific request requires an approved account.'],
  invalidContext: ['Ссылка на объект неполная. Опишите ситуацию в общем обращении.', 'Нысан сілтемесі толық емес. Жағдайды жалпы өтініште сипаттаңыз.', 'The item link is incomplete. Describe the issue in a general request.'],
  reason: ['Опишите ситуацию', 'Жағдайды сипаттаңыз', 'Describe the issue'],
  reasonHint: ['От 10 до 3000 символов. Укажите, что произошло и какую помощь ожидаете.', '10–3000 таңба. Не болғанын және қандай көмек керегін жазыңыз.', '10–3000 characters. Explain what happened and the help you need.'],
  submit: ['Отправить обращение', 'Өтінішті жіберу', 'Submit request'],
  created: ['Обращение отправлено', 'Өтініш жіберілді', 'Request submitted'],
  all: ['Все статусы', 'Барлық мәртебелер', 'All statuses'],
  pending: ['Ожидает ответа', 'Жауап күтілуде', 'Awaiting reply'],
  reviewing: ['В работе', 'Қаралуда', 'In progress'],
  resolved: ['Решено', 'Шешілді', 'Resolved'],
  dismissed: ['Закрыто без решения', 'Шешімсіз жабылды', 'Dismissed'],
  mine: ['Мои обращения', 'Менің өтініштерім', 'My requests'],
  empty: ['Обращений пока нет', 'Әзірге өтініш жоқ', 'No requests yet'],
  filteredEmpty: ['По этому статусу обращений нет', 'Бұл мәртебеде өтініш жоқ', 'No requests with this status'],
  view: ['Открыть переписку', 'Хат алмасуды ашу', 'Open conversation'],
  close: ['Закрыть переписку', 'Хат алмасуды жабу', 'Close conversation'],
  refresh: ['Обновить', 'Жаңарту', 'Refresh'],
  previous: ['Предыдущие обращения', 'Алдыңғы өтініштер', 'Previous requests'],
  next: ['Следующие обращения', 'Келесі өтініштер', 'Next requests'],
  page: ['Страница', 'Бет', 'Page'],
  conversation: ['Переписка по обращению', 'Өтініш бойынша хат алмасу', 'Request conversation'],
  original: ['Первоначальное обращение', 'Бастапқы өтініш', 'Original request'],
  noReplies: ['Ответов пока нет', 'Әзірге жауап жоқ', 'No replies yet'],
  you: ['Вы', 'Сіз', 'You'],
  staff: ['Поддержка', 'Қолдау', 'Support'],
  participant: ['Участник', 'Қатысушы', 'Participant'],
  reply: ['Ваше сообщение', 'Сіздің хабарламаңыз', 'Your message'],
  replyHint: ['От 5 до 3000 символов.', '5–3000 таңба.', '5–3000 characters.'],
  send: ['Отправить сообщение', 'Хабарлама жіберу', 'Send message'],
  sent: ['Сообщение отправлено', 'Хабарлама жіберілді', 'Message sent'],
  older: ['Более ранние сообщения', 'Ертеректегі хабарламалар', 'Older messages'],
  newer: ['Более новые сообщения', 'Жаңарақ хабарламалар', 'Newer messages'],
  latest: ['Последние сообщения', 'Соңғы хабарламалар', 'Latest messages'],
  reopen: ['Ваш новый ответ откроет это обращение снова и переведёт его в ожидание ответа.', 'Жаңа жауабыңыз өтінішті қайта ашып, жауап күту мәртебесіне ауыстырады.', 'Your next reply will reopen this request and return it to awaiting reply.'],
  suspended: ['Отправка обращений и сообщений недоступна для приостановленного аккаунта. Историю можно прочитать.', 'Тоқтатылған есептік жазба өтініш не хабарлама жібере алмайды. Тарихты оқуға болады.', 'Suspended accounts cannot submit requests or messages. You can read the history.'],
  decision: ['Пояснение решения для участника', 'Қатысушыға шешім түсіндірмесі', 'Decision explanation for the participant'],
  decisionNote: ['Это пояснение появится в переписке участника. Пишите понятный ответ; внутренние заметки сюда не добавляйте.', 'Бұл түсіндірме қатысушының хат алмасуында көрінеді. Түсінікті жауап жазыңыз; ішкі жазбаларды қоспаңыз.', 'This explanation will appear in the participant’s conversation. Write a clear reply; do not include internal notes.'],
} as const;
export type SupportPhrase = keyof typeof phrases;
export function supportText(locale: SupportLocale, key: SupportPhrase) {
  return phrases[key][locale === 'ru' ? 0 : locale === 'kk' ? 1 : 2];
}
export type Report = {id:string;entity_type:string;entity_id:string;reason:string;status:string;created_at:string};
export type ReportMessage = {id:string;report_id:string;body:string;created_at:string;is_mine:boolean;sender_role:'support'|'participant'};
export function reportStatus(status: string): SupportPhrase {
  return ['pending','reviewing','resolved','dismissed'].includes(status) ? status as SupportPhrase : 'pending';
}
