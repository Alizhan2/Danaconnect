export type DemoLocale = 'ru' | 'kk' | 'en';
export type DemoDirection = 'it' | 'psychology' | 'education';
export type DemoLocalized<T> = Record<DemoLocale, T>;

export type DemoMentor = {
  id: string;
  name: string;
  city: DemoLocalized<string>;
  direction: DemoDirection;
  title: DemoLocalized<string>;
  bio: DemoLocalized<string>;
  expertise: DemoLocalized<string[]>;
  experienceYears: number;
  capacity: number;
  occupied: number;
  languages: string[];
  format: DemoLocalized<string>;
  help: DemoLocalized<string[]>;
};

export const demoDirections: { id: DemoDirection; label: DemoLocalized<string> }[] = [
  { id: 'it', label: { ru: 'IT', kk: 'IT', en: 'IT' } },
  { id: 'psychology', label: { ru: 'Психология', kk: 'Психология', en: 'Psychology' } },
  { id: 'education', label: { ru: 'Образование', kk: 'Білім беру', en: 'Education' } },
];

/** Fictional presentation fixtures. Never write these profiles to participant storage. */
export const demoMentors: DemoMentor[] = [
  {
    id: 'dana-backend', name: 'Дана · Demo',
    city: { ru: 'Алматы', kk: 'Алматы', en: 'Almaty' }, direction: 'it',
    title: { ru: 'Наставница по веб-разработке', kk: 'Веб-әзірлеу тәлімгері', en: 'Web development mentor' },
    bio: {
      ru: 'Вымышленный профиль наставницы, которая помогает пройти путь от первой идеи до работающего веб-проекта. В демо показан опыт с Python, API и командной разработкой.',
      kk: 'Алғашқы идеядан жұмыс істейтін веб-жобаға дейін көмектесетін тәлімгердің ойдан шығарылған профилі. Демода Python, API және командалық әзірлеу тәжірибесі көрсетілген.',
      en: 'A fictional mentor who helps turn a first idea into a working web project. This demo illustrates experience with Python, APIs and collaborative development.',
    },
    expertise: { ru: ['Python', 'Веб-разработка', 'API'], kk: ['Python', 'Веб-әзірлеу', 'API'], en: ['Python', 'Web development', 'APIs'] },
    experienceYears: 6, capacity: 3, occupied: 1, languages: ['RU', 'KK', 'EN'],
    format: { ru: 'Онлайн · раз в неделю', kk: 'Онлайн · аптасына бір рет', en: 'Online · once a week' },
    help: {
      ru: ['Составить план первого веб-проекта', 'Разобрать архитектуру и код', 'Подготовить портфолио для стажировки'],
      kk: ['Алғашқы веб-жобаның жоспарын құру', 'Архитектура мен кодты талдау', 'Тағылымдамаға арналған портфолио дайындау'],
      en: ['Plan a first web project', 'Review architecture and code', 'Prepare a portfolio for an internship'],
    },
  },
  {
    id: 'amina-data', name: 'Амина · Demo',
    city: { ru: 'Астана', kk: 'Астана', en: 'Astana' }, direction: 'it',
    title: { ru: 'Наставница по аналитике данных', kk: 'Деректерді талдау тәлімгері', en: 'Data analytics mentor' },
    bio: {
      ru: 'Вымышленный профиль для знакомства с направлением аналитики. Пример наставничества: выбрать учебный набор данных, сформулировать вопрос и понятно представить результат.',
      kk: 'Деректерді талдау бағытымен танысуға арналған ойдан шығарылған профиль. Тәлімгерлік мысалы: оқу деректерін таңдау, сұрақ қою және нәтижені түсінікті ұсыну.',
      en: 'A fictional profile introducing the data analytics track. An example journey covers choosing a practice dataset, asking a useful question and presenting the result clearly.',
    },
    expertise: { ru: ['SQL', 'Аналитика', 'Визуализация данных'], kk: ['SQL', 'Аналитика', 'Деректерді визуализациялау'], en: ['SQL', 'Analytics', 'Data visualization'] },
    experienceYears: 5, capacity: 2, occupied: 1, languages: ['RU', 'EN'],
    format: { ru: 'Онлайн · раз в две недели', kk: 'Онлайн · екі аптада бір рет', en: 'Online · every two weeks' },
    help: {
      ru: ['Выбрать задачу для аналитического проекта', 'Разобрать SQL и обработку данных', 'Подготовить презентацию результатов'],
      kk: ['Аналитикалық жобаға тапсырма таңдау', 'SQL мен деректерді өңдеуді талдау', 'Нәтижелердің таныстырылымын дайындау'],
      en: ['Choose an analytics project question', 'Explore SQL and data preparation', 'Prepare a presentation of the findings'],
    },
  },
  {
    id: 'mira-development', name: 'Мира · Demo',
    city: { ru: 'Актобе', kk: 'Ақтөбе', en: 'Aktobe' }, direction: 'psychology',
    title: { ru: 'Наставница по личному развитию', kk: 'Жеке даму тәлімгері', en: 'Personal development mentor' },
    bio: {
      ru: 'Вымышленный профиль о целях, привычках и устойчивом темпе учёбы. Этот пример показывает формат наставничества; он не предлагает диагностику или психологическое лечение.',
      kk: 'Мақсаттар, әдеттер және тұрақты оқу қарқыны туралы ойдан шығарылған профиль. Бұл мысал тәлімгерлік форматын көрсетеді; диагностика немесе психологиялық ем ұсынбайды.',
      en: 'A fictional profile focused on goals, habits and a sustainable study pace. This example shows a mentoring format and does not offer diagnosis or psychological treatment.',
    },
    expertise: { ru: ['Постановка целей', 'Привычки', 'Учебный баланс'], kk: ['Мақсат қою', 'Әдеттер', 'Оқу тепе-теңдігі'], en: ['Goal setting', 'Habits', 'Study balance'] },
    experienceYears: 4, capacity: 3, occupied: 1, languages: ['RU', 'KK'],
    format: { ru: 'Онлайн · индивидуальные встречи', kk: 'Онлайн · жеке кездесулер', en: 'Online · individual meetings' },
    help: {
      ru: ['Сформулировать достижимую цель', 'Выстроить удобный учебный ритм', 'Отслеживать прогресс без перегрузки'],
      kk: ['Қолжетімді мақсат қою', 'Ыңғайлы оқу ырғағын қалыптастыру', 'Артық жүктемесіз ілгерілеуді бақылау'],
      en: ['Define an achievable goal', 'Build a comfortable study routine', 'Track progress without overload'],
    },
  },
  {
    id: 'aiya-communication', name: 'Айя · Demo',
    city: { ru: 'Караганда', kk: 'Қарағанды', en: 'Karaganda' }, direction: 'psychology',
    title: { ru: 'Наставница по коммуникации', kk: 'Қарым-қатынас тәлімгері', en: 'Communication mentor' },
    bio: {
      ru: 'Вымышленная наставница по общению в учебных и проектных командах. Профиль иллюстрирует работу с обратной связью, публичными выступлениями и распределением ответственности.',
      kk: 'Оқу және жоба командаларындағы қарым-қатынас бойынша ойдан шығарылған тәлімгер. Профиль кері байланыс, көпшілік алдында сөйлеу және жауапкершілікті бөлу жұмысын көрсетеді.',
      en: 'A fictional mentor for communication in study and project teams. The profile illustrates feedback skills, public speaking and sharing responsibilities.',
    },
    expertise: { ru: ['Коммуникация', 'Обратная связь', 'Командная работа'], kk: ['Қарым-қатынас', 'Кері байланыс', 'Командалық жұмыс'], en: ['Communication', 'Feedback', 'Teamwork'] },
    experienceYears: 7, capacity: 2, occupied: 2, languages: ['RU', 'KK', 'EN'],
    format: { ru: 'Онлайн · практические упражнения', kk: 'Онлайн · практикалық жаттығулар', en: 'Online · practical exercises' },
    help: {
      ru: ['Подготовить короткое выступление', 'Научиться давать понятную обратную связь', 'Обсудить взаимодействие в команде'],
      kk: ['Қысқа сөз сөйлеуді дайындау', 'Түсінікті кері байланыс беруді үйрену', 'Командадағы өзара әрекетті талқылау'],
      en: ['Prepare a short presentation', 'Practice clear and useful feedback', 'Discuss team collaboration'],
    },
  },
  {
    id: 'sara-edtech', name: 'Сара · Demo',
    city: { ru: 'Шымкент', kk: 'Шымкент', en: 'Shymkent' }, direction: 'education',
    title: { ru: 'Наставница по образовательным проектам', kk: 'Білім беру жобаларының тәлімгері', en: 'Education project mentor' },
    bio: {
      ru: 'Вымышленный профиль для тех, кто хочет создать учебный курс, клуб или образовательный сервис. Пример помогает увидеть путь от потребностей учеников до небольшого пилота.',
      kk: 'Оқу курсын, клубын немесе білім беру сервисін жасағысы келетіндерге арналған ойдан шығарылған профиль. Мысал оқушы қажеттіліктерінен шағын пилотқа дейінгі жолды көрсетеді.',
      en: 'A fictional profile for people creating a course, learning club or educational service. This example shows a path from learner needs to a small pilot.',
    },
    expertise: { ru: ['EdTech', 'Учебные программы', 'Пилотные проекты'], kk: ['EdTech', 'Оқу бағдарламалары', 'Пилоттық жобалар'], en: ['EdTech', 'Learning design', 'Pilot projects'] },
    experienceYears: 8, capacity: 3, occupied: 0, languages: ['RU', 'KK'],
    format: { ru: 'Онлайн · работа над проектом', kk: 'Онлайн · жобамен жұмыс', en: 'Online · project sessions' },
    help: {
      ru: ['Определить аудиторию и учебную цель', 'Собрать программу и задания', 'Запустить небольшой учебный пилот'],
      kk: ['Аудитория мен оқу мақсатын анықтау', 'Бағдарлама мен тапсырмалар құрастыру', 'Шағын оқу пилотын іске қосу'],
      en: ['Define the audience and learning goal', 'Design a programme and activities', 'Launch a small learning pilot'],
    },
  },
  {
    id: 'alua-study', name: 'Алуа · Demo',
    city: { ru: 'Уральск', kk: 'Орал', en: 'Oral' }, direction: 'education',
    title: { ru: 'Наставница по учебной траектории', kk: 'Оқу жолын таңдау тәлімгері', en: 'Learning pathway mentor' },
    bio: {
      ru: 'Вымышленный профиль наставницы для выбора учебного направления и самостоятельного обучения. В демо показано, как связать интересы, навыки и понятный план на несколько недель.',
      kk: 'Оқу бағытын таңдау мен өздігінен білім алуға арналған тәлімгердің ойдан шығарылған профилі. Демода қызығушылықтарды, дағдыларды және бірнеше апталық жоспарды байланыстыру көрсетілген.',
      en: 'A fictional mentor profile for choosing a learning direction and studying independently. The demo connects interests, skills and a clear plan for the coming weeks.',
    },
    expertise: { ru: ['Самостоятельное обучение', 'Учебный план', 'Портфолио'], kk: ['Өздігінен оқу', 'Оқу жоспары', 'Портфолио'], en: ['Independent learning', 'Study planning', 'Portfolio'] },
    experienceYears: 5, capacity: 2, occupied: 1, languages: ['RU', 'KK', 'EN'],
    format: { ru: 'Онлайн · раз в две недели', kk: 'Онлайн · екі аптада бір рет', en: 'Online · every two weeks' },
    help: {
      ru: ['Выбрать приоритетные навыки', 'Составить план самостоятельного обучения', 'Собрать результаты в портфолио'],
      kk: ['Басым дағдыларды таңдау', 'Өздігінен оқу жоспарын құру', 'Нәтижелерді портфолиоға жинау'],
      en: ['Choose priority skills', 'Plan independent learning', 'Collect outcomes in a portfolio'],
    },
  },
];

export function getDemoMentor(id: string): DemoMentor | undefined {
  return demoMentors.find((mentor) => mentor.id === id);
}

export function getDemoDirectionLabel(direction: DemoDirection, locale: DemoLocale): string {
  return demoDirections.find((item) => item.id === direction)?.label[locale] ?? direction;
}

export const demoText: Record<DemoLocale, Record<string, string>> = {
  ru: {
    badge: 'Демо', title: 'Демо наставницы', subtitle: 'Познакомьтесь с примером каталога DanaConnect',
    disclaimer: 'Все профили, имена, опыт и доступные места здесь вымышлены. Это демонстрация платформы. Заявки не отправляются, а встречи не назначаются.',
    filterLabel: 'Направление', allDirections: 'Все направления', searchLabel: 'Поиск наставницы', searchPlaceholder: 'Имя, навык или город',
    availableOnly: 'Есть свободные места', mentorsCount: 'Наставниц', noResults: 'По этим фильтрам наставниц нет', resetFilters: 'Сбросить фильтры',
    profileCta: 'Посмотреть демо профиль', availability: 'Свободные места', full: 'Набор закрыт', experience: 'Пример опыта', experienceUnit: 'лет',
    city: 'Город', languages: 'Языки', format: 'Формат встреч', expertise: 'Направления помощи', about: 'О наставнице', help: 'С чем может помочь',
    back: 'Назад к демо наставницам', backToPlatform: 'Открыть платформу', applicationCta: 'Попробовать демо заявку',
    applicationTitle: 'Демо заявка', applicationDescription: 'Попробуйте заполнить пример заявки. Данные не сохраняются и никому не отправляются.',
    motivationLabel: 'С чем нужна помощь?', motivationPlaceholder: 'Например: хочу создать учебный сайт для вымышленного клуба',
    motivationHint: 'От 10 до 1000 символов. Используйте вымышленный пример без личных данных.',
    motivationError: 'Введите от 10 до 1000 символов без учёта пробелов в начале и конце.',
    occupied: 'Занято в примере', applicationClosed: 'В демо набор закрыт. Выберите наставницу со свободными местами.',
    submitApplication: 'Показать демо результат', applicationSuccess: 'Демо результат: заявка не отправлена',
    applicationSuccessDescription: 'Это демонстрация: заявка не создана, наставница не получила сообщение. В рабочей платформе заявка появится в личном кабинете.',
    close: 'Закрыть', tryAgain: 'Попробовать ещё раз', notFound: 'Демо профиль не найден', placesSuffix: 'из', realCatalog: 'Каталог настоящих наставниц',
    demoNotice: 'Вымышленный профиль · только для демонстрации', nameLabel: 'Имя', namePlaceholder: 'Как к вам обращаться',
  },
  kk: {
    badge: 'Демо', title: 'Демо тәлімгерлер', subtitle: 'DanaConnect каталогының мысалымен танысыңыз',
    disclaimer: 'Мұндағы барлық профильдер, есімдер, тәжірибе және бос орындар ойдан шығарылған. Бұл платформаның демонстрациясы. Өтінімдер жіберілмейді, кездесулер белгіленбейді.',
    filterLabel: 'Бағыт', allDirections: 'Барлық бағыттар', searchLabel: 'Тәлімгерді іздеу', searchPlaceholder: 'Есім, дағды немесе қала',
    availableOnly: 'Бос орындары бар', mentorsCount: 'Тәлімгерлер', noResults: 'Бұл сүзгілер бойынша тәлімгерлер жоқ', resetFilters: 'Сүзгілерді тазарту',
    profileCta: 'Демо профильді көру', availability: 'Бос орындар', full: 'Қабылдау жабық', experience: 'Тәжірибе мысалы', experienceUnit: 'жыл',
    city: 'Қала', languages: 'Тілдер', format: 'Кездесу форматы', expertise: 'Көмек бағыттары', about: 'Тәлімгер туралы', help: 'Қандай көмек көрсете алады',
    back: 'Демо тәлімгерлерге оралу', backToPlatform: 'Платформаны ашу', applicationCta: 'Демо өтінімді байқап көру',
    applicationTitle: 'Демо өтінім', applicationDescription: 'Өтінім мысалын толтырып көріңіз. Деректер сақталмайды және ешкімге жіберілмейді.',
    motivationLabel: 'Қандай көмек қажет?', motivationPlaceholder: 'Мысалы: ойдан шығарылған клубқа оқу сайтын жасағым келеді',
    motivationHint: '10–1000 таңба. Жеке деректерсіз ойдан шығарылған мысалды пайдаланыңыз.',
    motivationError: 'Басындағы және соңындағы бос орындарды есептемей, 10–1000 таңба енгізіңіз.',
    occupied: 'Мысалда толған орындар', applicationClosed: 'Демода қабылдау жабық. Бос орны бар тәлімгерді таңдаңыз.',
    submitApplication: 'Демо нәтижені көрсету', applicationSuccess: 'Демо нәтиже: өтінім жіберілген жоқ',
    applicationSuccessDescription: 'Бұл демонстрация: өтінім жасалған жоқ, тәлімгер хабарлама алған жоқ. Жұмыс платформасында өтінім жеке кабинетте пайда болады.',
    close: 'Жабу', tryAgain: 'Қайта байқап көру', notFound: 'Демо профиль табылмады', placesSuffix: 'жалпы', realCatalog: 'Нақты тәлімгерлер каталогы',
    demoNotice: 'Ойдан шығарылған профиль · тек демонстрация үшін', nameLabel: 'Есім', namePlaceholder: 'Сізге қалай жүгінейік',
  },
  en: {
    badge: 'Demo', title: 'Demo mentors', subtitle: 'Explore an example DanaConnect catalogue',
    disclaimer: 'All profiles, names, experience and available places here are fictional. This is a platform demonstration. Applications are not sent and meetings are not scheduled.',
    filterLabel: 'Track', allDirections: 'All tracks', searchLabel: 'Find a mentor', searchPlaceholder: 'Name, skill or city',
    availableOnly: 'Places available', mentorsCount: 'Mentors', noResults: 'No mentors match these filters', resetFilters: 'Reset filters',
    profileCta: 'View demo profile', availability: 'Available places', full: 'Intake closed', experience: 'Illustrative experience', experienceUnit: 'years',
    city: 'City', languages: 'Languages', format: 'Meeting format', expertise: 'Areas of expertise', about: 'About the mentor', help: 'How she can help',
    back: 'Back to demo mentors', backToPlatform: 'Open the platform', applicationCta: 'Try a demo application',
    applicationTitle: 'Demo application', applicationDescription: 'Try completing a sample application. Your input is not saved or sent to anyone.',
    motivationLabel: 'What would you like help with?', motivationPlaceholder: 'For example: I want to build a learning website for a fictional club',
    motivationHint: 'Use 10–1000 characters and a fictional example without personal information.',
    motivationError: 'Enter 10–1000 characters, excluding spaces at the beginning and end.',
    occupied: 'Illustrative occupied places', applicationClosed: 'Demo intake is closed. Choose a mentor with available places.',
    submitApplication: 'Show demo result', applicationSuccess: 'Demo result: application not sent',
    applicationSuccessDescription: 'This is a demonstration: no application was created and no mentor received a message. On the live platform, an application would appear in your dashboard.',
    close: 'Close', tryAgain: 'Try again', notFound: 'Demo profile not found', placesSuffix: 'of', realCatalog: 'Real mentor catalogue',
    demoNotice: 'Fictional profile · for demonstration only', nameLabel: 'Name', namePlaceholder: 'How should we address you',
  },
};
