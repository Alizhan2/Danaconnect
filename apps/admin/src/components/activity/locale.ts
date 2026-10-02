"use client";
import { useLocale } from "@/lib/i18n";

const phrases: Record<string, readonly [string, string]> = {
  "Участия и встречи": [
    "Қатысу және кездесулер",
    "Participations and meetings",
  ],
  Участия: ["Қатысулар", "Participations"],
  Встречи: ["Кездесулер", "Meetings"],
  "Все статусы": ["Барлық мәртебелер", "All statuses"],
  Активно: ["Белсенді", "Active"],
  "На паузе": ["Үзілісте", "Paused"],
  "Успешно завершено": ["Сәтті аяқталды", "Completed successfully"],
  "Завершено досрочно": ["Мерзімінен бұрын аяқталды", "Completed early"],
  Запланировано: ["Жоспарланған", "Scheduled"],
  Отменено: ["Болдырылмады", "Cancelled"],
  Проведено: ["Өткізілді", "Completed"],
  Неявка: ["Қатыспады", "No show"],
  Менти: ["Менти", "Mentee"],
  Ментор: ["Ментор", "Mentor"],
  "Без проекта": ["Жобасыз", "Without a project"],
  "Начало участия": ["Қатысудың басталуы", "Participation started"],
  "Завершение участия": ["Қатысудың аяқталуы", "Participation ended"],
  "Причина паузы": ["Үзіліс себебі", "Reason for pausing"],
  "Поставить на паузу": ["Үзіліске қою", "Pause participation"],
  Возобновить: ["Жалғастыру", "Resume"],
  "Досрочное завершение": ["Мерзімінен бұрын аяқтау", "Early completion"],
  "Причина завершения": ["Аяқтау себебі", "Exit reason"],
  "Комментарий администратора": [
    "Әкімші түсініктемесі",
    "Administrator explanation",
  ],
  "Завершить досрочно": ["Мерзімінен бұрын аяқтау", "Complete early"],
  "Закрыть форму": ["Пішінді жабу", "Close form"],
  "Подтвердить досрочное завершение": [
    "Мерзімінен бұрын аяқтауды растау",
    "Confirm early completion",
  ],
  "Пауза и досрочное завершение отменят будущие встречи этого участия. Возобновление проверяет доступ участников заново.":
    [
      "Үзіліс пен мерзімінен бұрын аяқтау осы қатысудың болашақ кездесулерін болдырмайды. Жалғастыру қатысушылардың рұқсатын қайта тексереді.",
      "Pausing or completing early cancels future meetings for this participation. Resuming checks participant access again.",
    ],
  "Успешные результаты проверяются в разделе результатов. Проведение встречи подтверждает её ментор.":
    [
      "Сәтті нәтижелер нәтижелер бөлімінде тексеріледі. Кездесудің өткізілгенін оның менторы растайды.",
      "Successful outcomes are reviewed in Outcomes. Meeting completion is confirmed by its mentor.",
    ],
  "Недостаточно времени": ["Уақыт жеткіліксіз", "Not enough time"],
  "Изменились интересы": ["Қызығушылықтар өзгерді", "Interests changed"],
  "Не подошёл формат менторства": [
    "Менторлық форматы сәйкес келмеді",
    "Mentorship format did not fit",
  ],
  "Технические трудности": ["Техникалық қиындықтар", "Technical difficulties"],
  "Личные обстоятельства": ["Жеке жағдайлар", "Personal circumstances"],
  "Другая причина": ["Басқа себеп", "Other reason"],
  "Причины завершения недоступны. Повторите загрузку.": [
    "Аяқтау себептері қолжетімсіз. Қайта жүктеңіз.",
    "Exit reasons are unavailable. Retry loading.",
  ],
  "Открыть проект": ["Жобаны ашу", "Open project"],
  Обновить: ["Жаңарту", "Refresh"],
  "Изменения сохранены": ["Өзгерістер сақталды", "Changes saved"],
  "Встреча отменена": ["Кездесу болдырылмады", "Meeting cancelled"],
  "Отменить будущую встречу": [
    "Болашақ кездесуді болдырмау",
    "Cancel future meeting",
  ],
  "Подтвердить отмену встречи": [
    "Кездесуді болдырмауды растау",
    "Confirm meeting cancellation",
  ],
  "Встречу можно отменить только до её начала. Участники получат уведомление.":
    [
      "Кездесуді басталғанға дейін ғана болдырмауға болады. Қатысушыларға хабарлама жіберіледі.",
      "A meeting can only be cancelled before it starts. Participants receive a notification.",
    ],
  "Открыть ссылку встречи": ["Кездесу сілтемесін ашу", "Open meeting link"],
  "Часовой пояс встречи": ["Кездесудің уақыт белдеуі", "Meeting time zone"],
  Начало: ["Басталуы", "Starts"],
  Окончание: ["Аяқталуы", "Ends"],
  "Идентификатор участия": ["Қатысу идентификаторы", "Participation ID"],
  "Участие не привязано": ["Қатысуға байланыспаған", "No linked participation"],
  "Завершённое участие нельзя поставить на паузу": [
    "Аяқталған қатысуды үзіліске қоюға болмайды",
    "A completed participation cannot be paused",
  ],
  "Завершённое участие нельзя возобновить": [
    "Аяқталған қатысуды жалғастыруға болмайды",
    "A completed participation cannot be resumed",
  ],
  "Роль участника изменилась. Обратитесь к администратору": [
    "Қатысушының рөлі өзгерді. Әкімшіге хабарласыңыз",
    "A participant’s role has changed. Contact an administrator",
  ],
  "Участник не допущен к работе на платформе": [
    "Қатысушыға платформада жұмыс істеуге рұқсат берілмеген",
    "A participant does not have platform access",
  ],
  "Подтвердите актуальные обязательные документы": [
    "Қолданыстағы міндетті құжаттарды растаңыз",
    "Accept the current required documents",
  ],
  "Можно отменить только будущую запланированную встречу": [
    "Тек болашақ жоспарланған кездесуді болдырмауға болады",
    "Only a future scheduled meeting can be cancelled",
  ],
  "Данные изменились. Обновите страницу и повторите действие": [
    "Деректер өзгерді. Бетті жаңартып, қайталаңыз",
    "Data has changed. Refresh the page and retry",
  ],
  "Расписание изменилось. Обновите страницу и повторите действие": [
    "Кесте өзгерді. Бетті жаңартып, қайталаңыз",
    "The schedule has changed. Refresh the page and retry",
  ],
  "Проверьте заполнение полей": [
    "Өрістерді тексеріңіз",
    "Check the form fields",
  ],
};

export function useActivityLocale() {
  const context = useLocale();
  const tr = (phrase: string) =>
    context.locale === "ru"
      ? phrase
      : (phrases[phrase]?.[context.locale === "kk" ? 0 : 1] ?? phrase);
  const status = (value: string) =>
    tr(
      (
        {
          active: "Активно",
          paused: "На паузе",
          completed_successfully: "Успешно завершено",
          completed_early: "Завершено досрочно",
          scheduled: "Запланировано",
          cancelled: "Отменено",
          completed: "Проведено",
          no_show: "Неявка",
        } as Record<string, string>
      )[value] ?? value,
    );
  return { ...context, tr, status };
}
