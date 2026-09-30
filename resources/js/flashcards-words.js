/* ==========================================================================
   GLOSOR - THE WORDS, AND HOW AN ANSWER IS READ

   Everything flashcards.html knows about English and Spanish lives here,
   apart from the page, so it can be tested in Node (resources/tests/
   flashcards): the themes and their words, the cards made from them, how a
   typed answer is judged, the pupil's own word lists and the links that
   share them, and the Leitner boxes that say when a word is due again.

   A WORD is one line of a theme: the Swedish, the English and the Spanish,
   and a picture where one helps. Either language may be missing (Spanish
   says "tener hambre" where Swedish and English have an adjective). In a
   field, "|" separates answers that are all right ("mum|mom|mother"); the
   first is the one shown. " / " is shown as it is, and each side of it is
   right on its own ("mormor / farmor").

   A CARD is a word asked one way: "till" (Swedish on the front, the
   language on the back - producing the word, the harder skill) or "fran"
   (the other way round - recognising it). A few themes ask something else:
   the forms of an English irregular verb, el or la for a Spanish noun, and
   a Spanish verb in the present tense.

   Progress is kept per card KEY. The key is made from the words
   themselves, so "hund = dog" in the pupil's own list is the same card as
   in the theme Djur.
   ========================================================================== */

const FC_WORDS = (() => {
  'use strict';

  const LANGS = {
    en: { name: 'engelska', Name: 'Engelska', speech: ['en-GB', 'en-US', 'en-AU', 'en'] },
    es: { name: 'spanska', Name: 'Spanska', speech: ['es-ES', 'es-MX', 'es-US', 'es'] },
  };

  /* ── The themes ──────────────────────────────────────────────────────────
     w(svenska, english, español, picture): a picture is an emoji, or a
     colour for the theme Färger. null for a language leaves the word out of
     that language.                                                        */
  const w = (sv, en, es, pic) => ({ sv, en, es, pic: pic || null });

  const SV_NUMBERS = ['noll', 'ett|en', 'två', 'tre', 'fyra', 'fem', 'sex', 'sju', 'åtta', 'nio', 'tio', 'elva', 'tolv',
    'tretton', 'fjorton', 'femton', 'sexton', 'sjutton', 'arton', 'nitton', 'tjugo'];
  const SV_TENS = { 20: 'tjugo', 30: 'trettio', 40: 'fyrtio', 50: 'femtio', 60: 'sextio', 70: 'sjuttio', 80: 'åttio', 90: 'nittio' };
  const EN_NUMBERS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
    'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty'];
  const EN_TENS = { 20: 'twenty', 30: 'thirty', 40: 'forty', 50: 'fifty', 60: 'sixty', 70: 'seventy', 80: 'eighty', 90: 'ninety' };
  const ES_NUMBERS = ['cero', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve', 'diez', 'once', 'doce',
    'trece', 'catorce', 'quince', 'dieciséis', 'diecisiete', 'dieciocho', 'diecinueve', 'veinte'];
  const ES_VEINTI = ['veinte', 'veintiuno', 'veintidós', 'veintitrés', 'veinticuatro', 'veinticinco', 'veintiséis',
    'veintisiete', 'veintiocho', 'veintinueve'];
  const ES_TENS = { 30: 'treinta', 40: 'cuarenta', 50: 'cincuenta', 60: 'sesenta', 70: 'setenta', 80: 'ochenta', 90: 'noventa' };

  /** A number from 0 to 100 as a word. Swedish gives "ett|en" and similar. */
  function numberWord(n, lang) {
    if (!Number.isInteger(n) || n < 0 || n > 100) throw new RangeError(`numberWord: ${n}`);
    const tens = Math.floor(n / 10) * 10, ones = n % 10;
    if (lang === 'sv') {
      if (n <= 20) return SV_NUMBERS[n];
      if (n === 100) return 'hundra|etthundra';
      if (!ones) return SV_TENS[tens];
      return ones === 1 ? `${SV_TENS[tens]}ett|${SV_TENS[tens]}en` : SV_TENS[tens] + SV_NUMBERS[ones];
    }
    if (lang === 'en') {
      if (n <= 20) return EN_NUMBERS[n];
      if (n === 100) return 'one hundred|a hundred|hundred';
      return ones ? `${EN_TENS[tens]}-${EN_NUMBERS[ones]}` : EN_TENS[tens];
    }
    if (lang === 'es') {
      if (n <= 20) return ES_NUMBERS[n];
      if (n < 30) return ES_VEINTI[ones];
      if (n === 100) return 'cien';
      return ones ? `${ES_TENS[tens]} y ${ES_NUMBERS[ones]}` : ES_TENS[tens];
    }
    throw new Error(`numberWord: no language ${lang}`);
  }

  const numbers = list => list.map(n => w(`${n}|${numberWord(n, 'sv')}`, numberWord(n, 'en'), numberWord(n, 'es')));

  const GROUPS = [
    {
      id: 'forsta', title: 'Första orden', color: 'green', grade: { en: 'åk 1–3', es: 'åk 6' },
      desc: 'Färger, siffror, djur, familjen, kroppen och kläder – orden man börjar med.',
      topics: [
        {
          id: 'farger', title: 'Färger',
          words: [
            w('röd', 'red', 'rojo', '#e53935'), w('blå', 'blue', 'azul', '#1e6fd9'), w('gul', 'yellow', 'amarillo', '#fdd835'),
            w('grön', 'green', 'verde', '#43a047'), w('svart', 'black', 'negro', '#212121'), w('vit', 'white', 'blanco', '#ffffff'),
            w('rosa', 'pink', 'rosa', '#f48fb1'), w('lila', 'purple', 'morado|lila|violeta', '#8e44ad'),
            w('orange', 'orange', 'naranja|anaranjado', '#fb8c00'), w('brun', 'brown', 'marrón|café', '#795548'),
            w('grå', 'grey|gray', 'gris', '#9e9e9e'),
          ],
        },
        { id: 'siffror', title: 'Siffror 0–20', words: numbers([...Array(21).keys()]) },
        {
          id: 'husdjur', title: 'Djur hemma och på gården',
          words: [
            w('hund', 'dog', 'el perro', '🐶'), w('katt', 'cat', 'el gato', '🐱'), w('häst', 'horse', 'el caballo', '🐴'),
            w('ko', 'cow', 'la vaca', '🐄'), w('gris', 'pig', 'el cerdo', '🐷'), w('får', 'sheep', 'la oveja', '🐑'),
            w('höna', 'hen|chicken', 'la gallina', '🐔'), w('tupp', 'rooster|cock', 'el gallo', '🐓'), w('anka', 'duck', 'el pato', '🦆'),
            w('kanin', 'rabbit|bunny', 'el conejo', '🐰'), w('mus', 'mouse', 'el ratón', '🐭'), w('hamster', 'hamster', 'el hámster', '🐹'),
            w('fågel', 'bird', 'el pájaro', '🐦'), w('fisk', 'fish', 'el pez', '🐟'), w('get', 'goat', 'la cabra', '🐐'),
            w('sköldpadda', 'turtle|tortoise', 'la tortuga', '🐢'),
          ],
        },
        {
          id: 'familj', title: 'Familjen',
          words: [
            w('mamma', 'mum|mom|mother', 'la mamá|la madre', '👩'), w('pappa', 'dad|father', 'el papá|el padre', '👨'),
            w('syster', 'sister', 'la hermana'), w('bror', 'brother', 'el hermano'),
            w('syskon', 'brothers and sisters|siblings', 'los hermanos'), w('mormor / farmor', 'grandmother|grandma|granny', 'la abuela', '👵'),
            w('morfar / farfar', 'grandfather|grandpa', 'el abuelo', '👴'), w('föräldrar', 'parents', 'los padres'),
            w('familj', 'family', 'la familia', '👪'), w('barn', 'child|kid', 'el niño|la niña', '🧒'), w('bebis', 'baby', 'el bebé', '👶'),
            w('kusin', 'cousin', 'el primo|la prima'), w('moster / faster', 'aunt', 'la tía'), w('morbror / farbror', 'uncle', 'el tío'),
            w('dotter', 'daughter', 'la hija'), w('son', 'son', 'el hijo'),
          ],
        },
        {
          id: 'kropp', title: 'Kroppen',
          words: [
            w('huvud', 'head', 'la cabeza'), w('öga', 'eye', 'el ojo', '👁️'), w('öra', 'ear', 'la oreja', '👂'),
            w('näsa', 'nose', 'la nariz', '👃'), w('mun', 'mouth', 'la boca', '👄'), w('tand', 'tooth', 'el diente', '🦷'),
            w('hår', 'hair', 'el pelo|el cabello'), w('hand', 'hand', 'la mano', '✋'), w('arm', 'arm', 'el brazo', '💪'),
            w('ben', 'leg', 'la pierna', '🦵'), w('fot', 'foot', 'el pie', '🦶'), w('finger', 'finger', 'el dedo', '☝️'),
            w('knä', 'knee', 'la rodilla'), w('mage', 'stomach|tummy|belly', 'el estómago|la barriga|la tripa'),
            w('rygg', 'back', 'la espalda'), w('hals', 'neck', 'el cuello'), w('axel', 'shoulder', 'el hombro'),
            w('ansikte', 'face', 'la cara', '🙂'),
          ],
        },
        {
          id: 'klader', title: 'Kläder',
          words: [
            w('tröja', 'sweater|jumper|pullover', 'el jersey|el suéter'), w('byxor', 'trousers|pants', 'los pantalones', '👖'),
            w('klänning', 'dress', 'el vestido', '👗'), w('kjol', 'skirt', 'la falda'), w('skor', 'shoes', 'los zapatos', '👞'),
            w('strumpor', 'socks', 'los calcetines', '🧦'), w('mössa', 'hat|woolly hat|beanie', 'el gorro'),
            w('keps', 'cap', 'la gorra', '🧢'), w('jacka', 'jacket', 'la chaqueta', '🧥'),
            w('vantar', 'mittens|gloves', 'las manoplas|los guantes', '🧤'), w('halsduk', 'scarf', 'la bufanda', '🧣'),
            w('skjorta', 'shirt', 'la camisa', '👔'), w('t-shirt', 't-shirt|tee', 'la camiseta', '👕'),
            w('shorts', 'shorts', 'los pantalones cortos', '🩳'), w('stövlar', 'boots', 'las botas', '👢'),
            w('pyjamas', 'pyjamas|pajamas', 'el pijama'),
          ],
        },
      ],
    },
    {
      id: 'vardag', title: 'Vardagen', color: 'blue', grade: { en: 'åk 3–6', es: 'åk 6–7' },
      desc: 'Mat, skolan, hemma, dagar och månader, och vädret.',
      topics: [
        {
          id: 'mat', title: 'Mat och dryck',
          words: [
            w('bröd', 'bread', 'el pan', '🍞'), w('smör', 'butter', 'la mantequilla', '🧈'), w('ost', 'cheese', 'el queso', '🧀'),
            w('mjölk', 'milk', 'la leche', '🥛'), w('vatten', 'water', 'el agua', '💧'), w('juice', 'juice', 'el zumo|el jugo', '🧃'),
            w('ägg', 'egg', 'el huevo', '🥚'), w('kyckling', 'chicken', 'el pollo', '🍗'), w('kött', 'meat', 'la carne', '🥩'),
            w('ris', 'rice', 'el arroz', '🍚'), w('pasta', 'pasta', 'la pasta', '🍝'), w('soppa', 'soup', 'la sopa', '🍲'),
            w('glass', 'ice cream', 'el helado', '🍦'), w('tårta', 'cake', 'la tarta|el pastel', '🍰'),
            w('kaka', 'biscuit|cookie', 'la galleta', '🍪'), w('godis', 'sweets|candy', 'los caramelos|los dulces|las golosinas', '🍬'),
            w('pizza', 'pizza', 'la pizza', '🍕'), w('frukost', 'breakfast', 'el desayuno'), w('lunch', 'lunch', 'el almuerzo|la comida'),
            w('middag', 'dinner', 'la cena'), w('socker', 'sugar', 'el azúcar'), w('salt', 'salt', 'la sal', '🧂'),
          ],
        },
        {
          id: 'frukt', title: 'Frukt och grönsaker',
          words: [
            w('äpple', 'apple', 'la manzana', '🍎'), w('banan', 'banana', 'el plátano|la banana', '🍌'),
            w('apelsin', 'orange', 'la naranja', '🍊'), w('päron', 'pear', 'la pera', '🍐'), w('jordgubbe', 'strawberry', 'la fresa|la frutilla', '🍓'),
            w('vindruva', 'grape', 'la uva', '🍇'), w('citron', 'lemon', 'el limón', '🍋'), w('melon', 'melon', 'el melón', '🍈'),
            w('ananas', 'pineapple', 'la piña', '🍍'), w('körsbär', 'cherry', 'la cereza', '🍒'), w('tomat', 'tomato', 'el tomate', '🍅'),
            w('gurka', 'cucumber', 'el pepino', '🥒'), w('morot', 'carrot', 'la zanahoria', '🥕'), w('potatis', 'potato', 'la patata|la papa', '🥔'),
            w('lök', 'onion', 'la cebolla', '🧅'), w('sallad', 'lettuce|salad', 'la lechuga|la ensalada', '🥬'), w('majs', 'corn|maize', 'el maíz', '🌽'),
            w('svamp', 'mushroom', 'la seta|el champiñón', '🍄'),
          ],
        },
        {
          id: 'skola', title: 'Skolan',
          words: [
            w('skola', 'school', 'la escuela|el colegio', '🏫'), w('lärare', 'teacher', 'el profesor|la profesora|el maestro|la maestra', '🧑‍🏫'),
            w('elev', 'pupil|student', 'el alumno|la alumna'), w('klassrum', 'classroom', 'la clase|el aula'),
            w('blyertspenna', 'pencil', 'el lápiz', '✏️'), w('penna', 'pen', 'el bolígrafo|el boli', '🖊️'),
            w('suddgummi', 'rubber|eraser', 'la goma|la goma de borrar'), w('linjal', 'ruler', 'la regla', '📏'),
            w('bok', 'book', 'el libro', '📕'), w('papper', 'paper', 'el papel', '📄'), w('sax', 'scissors', 'las tijeras', '✂️'),
            w('lim', 'glue', 'el pegamento'), w('ryggsäck / skolväska', 'backpack|schoolbag|rucksack|bag', 'la mochila', '🎒'),
            w('bänk', 'desk', 'el pupitre|la mesa'), w('tavla', 'board|whiteboard|blackboard', 'la pizarra'),
            w('dator', 'computer', 'el ordenador|la computadora', '💻'), w('rast', 'break|breaktime|recess|playtime', 'el recreo'),
            w('läxa', 'homework', 'los deberes|la tarea'), w('lektion', 'lesson', 'la clase|la lección'),
          ],
        },
        {
          id: 'hemma', title: 'Hemma',
          words: [
            w('hus', 'house', 'la casa', '🏠'), w('lägenhet', 'flat|apartment', 'el piso|el apartamento', '🏢'),
            w('kök', 'kitchen', 'la cocina'), w('sovrum', 'bedroom', 'el dormitorio|la habitación'),
            w('badrum', 'bathroom', 'el cuarto de baño|el baño', '🛁'), w('vardagsrum', 'living room|sitting room|lounge', 'el salón|la sala de estar'),
            w('dörr', 'door', 'la puerta', '🚪'), w('fönster', 'window', 'la ventana', '🪟'), w('bord', 'table', 'la mesa'),
            w('stol', 'chair', 'la silla', '🪑'), w('säng', 'bed', 'la cama', '🛏️'), w('soffa', 'sofa|couch', 'el sofá', '🛋️'),
            w('lampa', 'lamp|light', 'la lámpara', '💡'), w('kylskåp', 'fridge|refrigerator', 'la nevera|el frigorífico|el refrigerador'),
            w('trappa', 'stairs|staircase', 'la escalera'), w('golv', 'floor', 'el suelo'), w('tak', 'roof|ceiling', 'el techo|el tejado'),
            w('toalett', 'toilet', 'el váter|el inodoro', '🚽'), w('trädgård', 'garden|yard', 'el jardín', '🌷'),
          ],
        },
        {
          id: 'dagar', title: 'Veckodagar',
          words: [
            w('måndag', 'Monday', 'lunes'), w('tisdag', 'Tuesday', 'martes'), w('onsdag', 'Wednesday', 'miércoles'),
            w('torsdag', 'Thursday', 'jueves'), w('fredag', 'Friday', 'viernes'), w('lördag', 'Saturday', 'sábado'),
            w('söndag', 'Sunday', 'domingo'),
          ],
        },
        {
          id: 'manader', title: 'Månader',
          words: [
            w('januari', 'January', 'enero'), w('februari', 'February', 'febrero'), w('mars', 'March', 'marzo'),
            w('april', 'April', 'abril'), w('maj', 'May', 'mayo'), w('juni', 'June', 'junio'), w('juli', 'July', 'julio'),
            w('augusti', 'August', 'agosto'), w('september', 'September', 'septiembre|setiembre'), w('oktober', 'October', 'octubre'),
            w('november', 'November', 'noviembre'), w('december', 'December', 'diciembre'),
          ],
        },
        {
          id: 'vader', title: 'Väder och årstider',
          words: [
            w('sol', 'sun', 'el sol', '☀️'), w('regn', 'rain', 'la lluvia', '🌧️'), w('snö', 'snow', 'la nieve', '❄️'),
            w('vind', 'wind', 'el viento', '💨'), w('moln', 'cloud', 'la nube', '☁️'), w('åska', 'thunder|thunderstorm', 'el trueno|la tormenta', '⛈️'),
            w('dimma', 'fog|mist', 'la niebla', '🌫️'), w('regnbåge', 'rainbow', 'el arcoíris|el arco iris', '🌈'), w('is', 'ice', 'el hielo', '🧊'),
            w('vår', 'spring', 'la primavera', '🌸'), w('sommar', 'summer', 'el verano', '🏖️'), w('höst', 'autumn|fall', 'el otoño', '🍂'),
            w('vinter', 'winter', 'el invierno', '⛄'),
          ],
        },
      ],
    },
    {
      id: 'fritid', title: 'Fritid och världen', color: 'yellow', grade: { en: 'åk 4–6', es: 'åk 7' },
      desc: 'Vilda djur, sport och fritid, staden, känslor och tal upp till hundra.',
      topics: [
        {
          id: 'vilda', title: 'Vilda djur',
          words: [
            w('björn', 'bear', 'el oso', '🐻'), w('varg', 'wolf', 'el lobo', '🐺'), w('räv', 'fox', 'el zorro', '🦊'),
            w('älg', 'elk|moose', 'el alce'), w('lejon', 'lion', 'el león', '🦁'), w('tiger', 'tiger', 'el tigre', '🐯'),
            w('elefant', 'elephant', 'el elefante', '🐘'), w('giraff', 'giraffe', 'la jirafa', '🦒'), w('apa', 'monkey|ape', 'el mono', '🐒'),
            w('orm', 'snake', 'la serpiente', '🐍'), w('krokodil', 'crocodile', 'el cocodrilo', '🐊'), w('zebra', 'zebra', 'la cebra', '🦓'),
            w('uggla', 'owl', 'el búho', '🦉'), w('igelkott', 'hedgehog', 'el erizo', '🦔'), w('ekorre', 'squirrel', 'la ardilla', '🐿️'),
            w('val', 'whale', 'la ballena', '🐳'), w('haj', 'shark', 'el tiburón', '🦈'), w('pingvin', 'penguin', 'el pingüino', '🐧'),
          ],
        },
        {
          id: 'sport', title: 'Fritid och sport',
          words: [
            w('fotboll', 'football|soccer', 'el fútbol', '⚽'), w('handboll', 'handball', 'el balonmano', '🤾'), w('tennis', 'tennis', 'el tenis', '🎾'),
            w('ishockey', 'ice hockey|hockey', 'el hockey sobre hielo|el hockey', '🏒'), w('simning', 'swimming', 'la natación', '🏊'),
            w('ridning', 'riding|horse riding', 'la equitación', '🏇'), w('dans', 'dance|dancing', 'el baile|la danza', '💃'),
            w('musik', 'music', 'la música', '🎵'), w('film', 'film|movie', 'la película', '🎬'),
            w('datorspel', 'computer game|video game', 'el videojuego', '🎮'), w('gitarr', 'guitar', 'la guitarra', '🎸'),
            w('piano', 'piano', 'el piano', '🎹'), w('boll', 'ball', 'la pelota|el balón'), w('skidåkning', 'skiing', 'el esquí', '⛷️'),
          ],
        },
        {
          id: 'staden', title: 'Fordon och staden',
          words: [
            w('bil', 'car', 'el coche|el carro|el auto', '🚗'), w('buss', 'bus', 'el autobús|el bus', '🚌'), w('tåg', 'train', 'el tren', '🚆'),
            w('cykel', 'bike|bicycle', 'la bicicleta|la bici', '🚲'), w('båt', 'boat', 'el barco', '⛵'),
            w('flygplan', 'plane|aeroplane|airplane', 'el avión', '✈️'), w('lastbil', 'lorry|truck', 'el camión', '🚚'),
            w('tunnelbana', 'underground|tube|subway|metro', 'el metro', '🚇'), w('gata', 'street', 'la calle'),
            w('affär', 'shop|store', 'la tienda', '🏪'), w('sjukhus', 'hospital', 'el hospital', '🏥'), w('bibliotek', 'library', 'la biblioteca'),
            w('park', 'park', 'el parque', '🌳'), w('station', 'station', 'la estación', '🚉'), w('kyrka', 'church', 'la iglesia', '⛪'),
            w('restaurang', 'restaurant', 'el restaurante', '🍽️'), w('torg', 'square|market square', 'la plaza'), w('bro', 'bridge', 'el puente', '🌉'),
          ],
        },
        {
          id: 'kanslor', title: 'Känslor',
          words: [
            w('glad', 'happy|glad', 'contento|contenta|feliz', '😊'), w('ledsen', 'sad', 'triste', '😢'),
            w('arg', 'angry|cross|mad', 'enfadado|enfadada|enojado|enojada', '😠'), w('rädd', 'scared|afraid|frightened', 'asustado|asustada', '😨'),
            w('trött', 'tired', 'cansado|cansada', '😴'), w('hungrig', 'hungry', null, '😋'), w('törstig', 'thirsty', null),
            w('sjuk', 'ill|sick', 'enfermo|enferma', '🤒'), w('nervös', 'nervous', 'nervioso|nerviosa', '😬'),
            w('förvånad', 'surprised', 'sorprendido|sorprendida', '😲'), w('uttråkad', 'bored', 'aburrido|aburrida', '🥱'),
            w('lugn', 'calm', 'tranquilo|tranquila', '😌'), w('stolt', 'proud', 'orgulloso|orgullosa'), w('kär', 'in love', 'enamorado|enamorada', '😍'),
          ],
        },
        { id: 'tal', title: 'Tal 20–100', words: numbers([...Array(10).keys()].map(i => 20 + i).concat([30, 34, 40, 45, 50, 56, 60, 67, 70, 78, 80, 89, 90, 92, 100])) },
      ],
    },
    {
      id: 'meningar', title: 'Ord som bygger meningar', color: 'red', grade: { en: 'åk 4–6', es: 'åk 7–8' },
      desc: 'Verb, motsatser, frågeord, småord och fraser – det som behövs för att säga något själv.',
      topics: [
        {
          id: 'verb', title: 'Vanliga verb',
          words: [
            w('vara', 'be', 'ser|estar'), w('ha', 'have', 'tener'), w('göra', 'do|make', 'hacer'), w('gå', 'go|walk', 'ir|andar|caminar'),
            w('komma', 'come', 'venir'), w('se', 'see', 'ver'), w('äta', 'eat', 'comer'), w('dricka', 'drink', 'beber|tomar'),
            w('sova', 'sleep', 'dormir'), w('springa', 'run', 'correr'), w('simma', 'swim', 'nadar'), w('läsa', 'read', 'leer'),
            w('skriva', 'write', 'escribir'), w('prata', 'talk|speak', 'hablar'), w('lyssna', 'listen', 'escuchar'),
            w('spela', 'play', 'jugar|tocar'), w('köpa', 'buy', 'comprar'), w('bo', 'live', 'vivir'), w('tycka om', 'like', 'gustar'),
            w('hjälpa', 'help', 'ayudar'), w('arbeta / jobba', 'work', 'trabajar'), w('sjunga', 'sing', 'cantar'), w('dansa', 'dance', 'bailar'),
            w('rita', 'draw', 'dibujar'), w('öppna', 'open', 'abrir'), w('stänga', 'close|shut', 'cerrar'), w('ta', 'take', 'tomar|coger'),
            w('ge', 'give', 'dar'),
          ],
        },
        {
          id: 'motsatser', title: 'Motsatser',
          words: [
            w('stor', 'big|large', 'grande'), w('liten', 'small|little', 'pequeño|pequeña'), w('lång', 'long|tall', 'largo|larga|alto|alta'),
            w('kort', 'short', 'corto|corta|bajo|baja'), w('gammal', 'old', 'viejo|vieja|mayor'), w('ung', 'young', 'joven'),
            w('ny', 'new', 'nuevo|nueva'), w('varm', 'warm|hot', 'caliente|cálido|cálida'), w('kall', 'cold', 'frío|fría'),
            w('snabb', 'fast|quick', 'rápido|rápida'), w('långsam', 'slow', 'lento|lenta'), w('lätt', 'easy|light', 'fácil|ligero|ligera'),
            w('svår', 'difficult|hard', 'difícil'), w('tung', 'heavy', 'pesado|pesada'), w('ren', 'clean', 'limpio|limpia'),
            w('smutsig', 'dirty', 'sucio|sucia'), w('öppen', 'open', 'abierto|abierta'), w('stängd', 'closed|shut', 'cerrado|cerrada'),
            w('full', 'full', 'lleno|llena'), w('tom', 'empty', 'vacío|vacía'), w('dyr', 'expensive', 'caro|cara'),
            w('billig', 'cheap', 'barato|barata'), w('rik', 'rich', 'rico|rica'), w('fattig', 'poor', 'pobre'),
            w('bra', 'good', 'bueno|buena|bien'), w('dålig', 'bad', 'malo|mala|mal'),
            w('fin / vacker', 'beautiful|pretty|nice|lovely', 'bonito|bonita|hermoso|hermosa|guapo|guapa'), w('ful', 'ugly', 'feo|fea'),
          ],
        },
        {
          id: 'fragor', title: 'Frågeord',
          words: [
            w('vad', 'what', 'qué'), w('vem', 'who', 'quién'), w('var', 'where', 'dónde'), w('när', 'when', 'cuándo'),
            w('varför', 'why', 'por qué'), w('hur', 'how', 'cómo'), w('vilken / vilket', 'which', 'cuál'),
            w('hur många', 'how many', 'cuántos|cuántas'), w('hur mycket', 'how much', 'cuánto|cuánta'), w('hur gammal', 'how old', null),
          ],
        },
        {
          id: 'smaord', title: 'Småord: var är det?',
          words: [
            w('i', 'in', 'en'), w('på', 'on', 'en|sobre|encima de'), w('under', 'under|below', 'debajo de|bajo'),
            w('bakom', 'behind', 'detrás de'), w('framför', 'in front of', 'delante de'), w('bredvid', 'next to|beside', 'al lado de'),
            w('mellan', 'between', 'entre'), w('över', 'over|above', 'encima de|sobre'), w('med', 'with', 'con'), w('utan', 'without', 'sin'),
            w('från', 'from', 'de|desde'), w('till', 'to', 'a|hacia'),
          ],
        },
        {
          id: 'fraser', title: 'Fraser',
          words: [
            w('hej', 'hello|hi', 'hola', '👋'), w('hej då', 'goodbye|bye|see you', 'adiós|hasta luego|chao'),
            w('tack', 'thank you|thanks', 'gracias'), w('tack så mycket', 'thank you very much|thanks a lot', 'muchas gracias'),
            w('varsågod', "you're welcome|here you are", 'de nada|aquí tienes'), w('förlåt', 'sorry', 'perdón|lo siento'),
            w('ursäkta', 'excuse me', 'perdone|disculpe|perdona|disculpa'), w('ja', 'yes', 'sí'), w('nej', 'no', 'no'),
            w('snälla', 'please', 'por favor'), w('god morgon', 'good morning', 'buenos días'), w('god natt', 'good night', 'buenas noches'),
            w('vad heter du?', "what's your name?|what is your name?", '¿cómo te llamas?'), w('jag heter …', 'my name is …|I am called …|I\'m called …', 'me llamo …'),
            w('hur mår du?', 'how are you?', '¿cómo estás?|¿qué tal?'), w('jag mår bra', "I'm fine|I am fine|I'm good|I am good|I'm OK", 'estoy bien|bien'),
            w('hur gammal är du?', 'how old are you?', '¿cuántos años tienes?'), w('jag är tolv år', "I'm twelve|I am twelve|I'm twelve years old|I am twelve years old", 'tengo doce años'),
            w('var bor du?', 'where do you live?', '¿dónde vives?'), w('jag bor i Sverige', 'I live in Sweden', 'vivo en Suecia'),
            w('jag förstår inte', "I don't understand|I do not understand", 'no entiendo|no comprendo'),
            w('jag är hungrig', "I'm hungry|I am hungry", 'tengo hambre'), w('jag är törstig', "I'm thirsty|I am thirsty", 'tengo sed'),
            w('jag fryser', "I'm cold|I am cold", 'tengo frío'), w('jag är rädd', "I'm scared|I am scared|I'm afraid", 'tengo miedo'),
          ],
        },
      ],
    },
    {
      id: 'grammatik', title: 'Grammatik', color: 'purple', grade: { en: 'åk 5–9', es: 'åk 7–9' },
      desc: { en: 'Oregelbundna verb: de tre formerna ska sitta – go, went, gone.', es: 'El eller la, och verben i presens: soy, eres, es …' },
      topics: [
        { id: 'irr1', title: 'Oregelbundna verb 1', lang: 'en', kind: 'forms', verbs: 'IRR1' },
        { id: 'irr2', title: 'Oregelbundna verb 2', lang: 'en', kind: 'forms', verbs: 'IRR2' },
        { id: 'genus', title: 'El eller la?', lang: 'es', kind: 'genus' },
        { id: 'konj1', title: 'Ser, estar och tener', lang: 'es', kind: 'konj', verbs: ['ser', 'estar', 'tener'] },
        { id: 'konj2', title: 'Ir och regelbundna verb', lang: 'es', kind: 'konj', verbs: ['ir', 'hablar', 'comer', 'vivir'] },
      ],
    },
  ];

  /* English irregular verbs: Swedish, the base form, the past tense
     (preteritum) and the past participle (perfekt particip), the most used
     first. */
  const IRREGULAR = {
    IRR1: [
      ['vara', 'be', 'was|were', 'been'], ['ha', 'have', 'had', 'had'], ['göra', 'do', 'did', 'done'], ['gå, åka', 'go', 'went', 'gone'],
      ['komma', 'come', 'came', 'come'], ['se', 'see', 'saw', 'seen'], ['äta', 'eat', 'ate', 'eaten'], ['dricka', 'drink', 'drank', 'drunk'],
      ['ge', 'give', 'gave', 'given'], ['ta', 'take', 'took', 'taken'], ['få', 'get', 'got', 'got|gotten'], ['göra, tillverka', 'make', 'made', 'made'],
      ['säga', 'say', 'said', 'said'], ['veta, känna till', 'know', 'knew', 'known'], ['tänka, tycka', 'think', 'thought', 'thought'],
      ['skriva', 'write', 'wrote', 'written'], ['läsa', 'read', 'read', 'read'], ['springa', 'run', 'ran', 'run'], ['simma', 'swim', 'swam', 'swum'],
      ['sjunga', 'sing', 'sang', 'sung'], ['börja', 'begin', 'began', 'begun'], ['köpa', 'buy', 'bought', 'bought'],
      ['ta med sig', 'bring', 'brought', 'brought'], ['hitta', 'find', 'found', 'found'], ['sova', 'sleep', 'slept', 'slept'],
    ],
    IRR2: [
      ['sitta', 'sit', 'sat', 'sat'], ['stå', 'stand', 'stood', 'stood'], ['tala', 'speak', 'spoke', 'spoken'], ['ha sönder', 'break', 'broke', 'broken'],
      ['flyga', 'fly', 'flew', 'flown'], ['glömma', 'forget', 'forgot', 'forgotten'], ['förlora, tappa bort', 'lose', 'lost', 'lost'],
      ['träffa', 'meet', 'met', 'met'], ['betala', 'pay', 'paid', 'paid'], ['lägga, sätta', 'put', 'put', 'put'], ['berätta', 'tell', 'told', 'told'],
      ['förstå', 'understand', 'understood', 'understood'], ['vinna', 'win', 'won', 'won'], ['välja', 'choose', 'chose', 'chosen'],
      ['falla, ramla', 'fall', 'fell', 'fallen'], ['känna', 'feel', 'felt', 'felt'], ['höra', 'hear', 'heard', 'heard'], ['behålla', 'keep', 'kept', 'kept'],
      ['lämna, gå', 'leave', 'left', 'left'], ['skicka', 'send', 'sent', 'sent'], ['lära ut', 'teach', 'taught', 'taught'],
      ['ha på sig', 'wear', 'wore', 'worn'], ['köra', 'drive', 'drove', 'driven'], ['rida, åka', 'ride', 'rode', 'ridden'], ['kasta', 'throw', 'threw', 'thrown'],
    ],
  };

  /* Spanish verbs in the present tense, yo … ellos. */
  const PERSONS = ['yo', 'tú', 'él / ella', 'nosotros', 'vosotros', 'ellos / ellas'];
  const CONJ = {
    ser: { sv: 'vara', forms: ['soy', 'eres', 'es', 'somos', 'sois', 'son'] },
    estar: { sv: 'vara, befinna sig', forms: ['estoy', 'estás', 'está', 'estamos', 'estáis', 'están'] },
    tener: { sv: 'ha', forms: ['tengo', 'tienes', 'tiene', 'tenemos', 'tenéis', 'tienen'] },
    ir: { sv: 'gå, åka', forms: ['voy', 'vas', 'va', 'vamos', 'vais', 'van'] },
    hablar: { sv: 'prata', forms: ['hablo', 'hablas', 'habla', 'hablamos', 'habláis', 'hablan'] },
    comer: { sv: 'äta', forms: ['como', 'comes', 'come', 'comemos', 'coméis', 'comen'] },
    vivir: { sv: 'bo, leva', forms: ['vivo', 'vives', 'vive', 'vivimos', 'vivís', 'viven'] },
  };

  /* ── Reading an answer ───────────────────────────────────────────────── */

  const ARTICLES = {
    en: ['a', 'an', 'the', 'to'],
    sv: ['en', 'ett', 'att'],
    es: ['el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas'],
  };
  const ES_PRONOUNS = ['yo', 'tu', 'el', 'ella', 'usted', 'nosotros', 'nosotras', 'vosotros', 'vosotras', 'ellos', 'ellas', 'ustedes'];

  /** Alternatives of a field: "a|b" and "c / d" are each right on their own. */
  function alternatives(field) {
    const out = [];
    for (const part of String(field).split('|')) {
      out.push(part.trim());
      if (part.includes(' / ')) for (const side of part.split(' / ')) out.push(side.trim());
    }
    return [...new Set(out.filter(Boolean))];
  }

  const shown = field => String(field).split('|')[0].trim();

  /* Diacritics, for the languages where a missing one is a spelling slip:
     é for e, ñ for n, ü for u. Never for Swedish, where å, ä and ö are
     letters of their own. */
  const stripAccents = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').normalize('NFC');

  /**
   * An answer as it is compared: lower case, no punctuation, apostrophes
   * dropped ("what's" = "whats"), dashes as spaces ("twenty-one"), and the
   * "…" that marks a gap in a phrase gone.
   */
  function normalize(s) {
    return String(s ?? '')
      .normalize('NFC')
      .toLocaleLowerCase('sv')
      .replace(/[’‘'`´]/g, '')
      .replace(/[-‐-―]/g, ' ')
      .replace(/[.,!?¡¿;:"«»()…“”]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function splitArticle(s, lang) {
    const words = s.split(' ');
    if (words.length > 1 && (ARTICLES[lang] || []).includes(words[0])) return { article: words[0], core: words.slice(1).join(' ') };
    return { article: '', core: s };
  }

  /* Edits between two words, a swap of two neighbours counting as one: "wnet"
     is one slip from "went", as a child would see it. */
  function levenshtein(a, b) {
    if (a === b) return 0;
    const m = a.length, n = b.length;
    if (!m) return n;
    if (!n) return m;
    const d = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)]);
    for (let j = 0; j <= n; j++) d[0][j] = j;
    for (let i = 1; i <= m; i++) {
      for (let j = 1; j <= n; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
        if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
      }
    }
    return d[m][n];
  }

  /* How far off a word may be and still be "almost": one letter from four
     letters on, two from ten. */
  const slack = s => (s.length >= 10 ? 2 : s.length >= 4 ? 1 : 0);

  /**
   * Judge a typed answer against the accepted ones.
   *
   * @param {string} typed
   * @param {string[]} accepted - every right answer; the first is the one shown
   * @param {Object} opts
   * @param {'sv'|'en'|'es'} opts.lang - the language of the answer
   * @param {'valfri'|'krav'} [opts.accents] - Spanish accents: may be left out, or must be there
   * @param {'valfri'|'krav'} [opts.article] - Spanish articles: may be left out, or must be there
   * @returns {{ok: boolean, verdict: string, best: string, note: string}}
   *   verdict: 'right', 'accent', 'article', 'almost', 'empty' or 'wrong'.
   *   ok says whether it counts as right; note says what to learn from it.
   */
  function check(typed, accepted, opts = {}) {
    const lang = opts.lang || 'en';
    const t = normalize(typed);
    if (!t) return { ok: false, verdict: 'empty', best: accepted[0], note: '' };
    const accentsMatter = lang === 'es' && opts.accents === 'krav';
    const articleMatters = lang === 'es' && opts.article === 'krav';
    const foldable = lang !== 'sv';
    const tSplit = splitArticle(t, lang);
    let almost = null;
    let accentMiss = null;
    let articleMiss = null;

    for (const raw of accepted) {
      const a = normalize(raw);
      if (t === a) return caseNote(typed, raw, lang);
      /* "jag heter …": the name is the child's own. */
      if (raw.includes('…') && a && t.startsWith(`${a} `)) return { ok: true, verdict: 'right', best: raw, note: '' };
      const aSplit = splitArticle(a, lang);
      const sameCore = tSplit.core === aSplit.core;
      const foldedCore = foldable && stripAccents(tSplit.core) === stripAccents(aSplit.core);
      if (sameCore || foldedCore) {
        const articleOk = tSplit.article === aSplit.article || (!tSplit.article && !articleMatters) || (!aSplit.article && !!tSplit.article);
        if (!articleOk) {
          if (!articleMiss) articleMiss = { raw, missing: !tSplit.article };
          continue;
        }
        if (sameCore) {
          const note = aSplit.article && !tSplit.article && lang === 'es' ? `Rätt! Med artikel: ${raw}.` : '';
          return { ok: true, verdict: 'right', best: raw, note };
        }
        if (!accentMiss) accentMiss = raw;
        continue;
      }
      const d = levenshtein(foldable ? stripAccents(tSplit.core) : tSplit.core, foldable ? stripAccents(aSplit.core) : aSplit.core);
      if (d <= slack(aSplit.core) && (!almost || d < almost.d)) almost = { raw, d };
    }
    if (accentMiss) {
      return accentsMatter
        ? { ok: false, verdict: 'accent', best: accentMiss, note: `Nästan! Accenten fattas: ${accentMiss}.` }
        : { ok: true, verdict: 'right', best: accentMiss, note: `Rätt! Det stavas ${accentMiss}.` };
    }
    if (articleMiss) {
      return {
        ok: false, verdict: 'article', best: articleMiss.raw,
        note: articleMiss.missing ? `Glöm inte artikeln: ${articleMiss.raw}.` : `Fel artikel – det heter ${articleMiss.raw}.`,
      };
    }
    if (almost) return { ok: false, verdict: 'almost', best: almost.raw, note: `Nästan! Det stavas ${almost.raw}.` };
    return { ok: false, verdict: 'wrong', best: accepted[0], note: '' };
  }

  /* Right, and the case differs where it matters: English days, months and
     "I" have capitals, and a child should see how they are written. */
  function caseNote(typed, raw, lang) {
    const capitals = lang === 'en' && /[A-Z]/.test(raw) && String(typed).trim() !== raw && typed.trim().toLowerCase() === raw.toLowerCase();
    return { ok: true, verdict: 'right', best: raw, note: capitals ? `Rätt! Det skrivs ${raw}.` : '' };
  }

  /** The forms of an irregular verb, typed in one go: "went gone", "was/were, been". */
  function checkForms(typed, card) {
    let tokens = normalize(typed).replace(/\//g, ' ').split(' ').filter(Boolean);
    if (tokens.length > 2 && tokens[0] === normalize(card.base)) tokens = tokens.slice(1);
    const past = card.past.map(normalize), part = card.part.map(normalize);
    const best = `${card.past[0]} – ${card.part[0]}`;
    if (!tokens.length) return { ok: false, verdict: 'empty', best, note: '' };
    if (tokens.length < 2) return { ok: false, verdict: 'wrong', best, note: 'Skriv båda formerna: dåtid och perfekt particip.' };
    const last = tokens[tokens.length - 1], first = tokens.slice(0, -1);
    const pastOk = first.every(x => past.includes(x));
    const partOk = part.includes(last);
    if (pastOk && partOk) return { ok: true, verdict: 'right', best, note: '' };
    const near = (x, list) => list.some(y => levenshtein(x, y) <= slack(y));
    if ((pastOk || first.every(x => near(x, past))) && (partOk || near(last, part))) {
      return { ok: false, verdict: 'almost', best, note: `Nästan! Det stavas ${card.base} – ${best}.` };
    }
    return { ok: false, verdict: 'wrong', best, note: '' };
  }

  /** El or la: the first word is what counts, so "el perro" is right too. */
  function checkGenus(typed, card) {
    const first = normalize(typed).split(' ')[0];
    if (!first) return { ok: false, verdict: 'empty', best: card.answer, note: '' };
    const ok = first === card.answer;
    return { ok, verdict: ok ? 'right' : 'wrong', best: card.answer, note: '' };
  }

  /** A Spanish verb form, with or without its pronoun: "tengo", "yo tengo". */
  function checkKonj(typed, card, opts) {
    const words = normalize(typed).split(' ');
    while (words.length > 1 && ES_PRONOUNS.includes(stripAccents(words[0]))) words.shift();
    return check(words.join(' '), card.accept, { ...opts, lang: 'es' });
  }

  /** Judge an answer to any card. */
  function judge(card, typed, opts = {}) {
    if (card.kind === 'forms') return checkForms(typed, card);
    if (card.kind === 'genus') return checkGenus(typed, card);
    if (card.kind === 'konj') return checkKonj(typed, card, opts);
    return check(typed, card.accept, { ...opts, lang: card.answerLang });
  }

  /* ── Cards ───────────────────────────────────────────────────────────── */

  /** The core of an answer, for keys: normalized, without article or accents. */
  function core(field, lang) {
    const n = normalize(shown(field));
    const c = splitArticle(n, lang).core;
    return lang === 'sv' ? c : stripAccents(c);
  }

  /** One word, one way round. */
  function wordCard(word, lang, dir, topic) {
    const x = word[lang];
    const base = { topic, kind: 'word', dir, lang, pic: word.pic || null, word };
    const key = `${lang}|${dir}|${core(x, lang)}|${core(word.sv, 'sv')}`;
    if (dir === 'till') {
      return Object.assign(base, {
        key, front: { text: shown(word.sv), lang: 'sv' }, ask: LANGS[lang].name,
        accept: alternatives(x), answer: shown(x), answerLang: lang, say: shown(x),
      });
    }
    return Object.assign(base, {
      key, front: { text: shown(x), lang }, ask: 'svenska',
      accept: alternatives(word.sv), answer: shown(word.sv), answerLang: 'sv', say: shown(x),
    });
  }

  function formsCards(topic) {
    return IRREGULAR[topic.verbs].map(([sv, base, past, part]) => ({
      topic: topic.id, kind: 'forms', dir: 'form', lang: 'en', key: `en|form|${base}`,
      front: { text: base, lang: 'en' }, sub: sv, ask: 'dåtid och perfekt particip',
      base, past: alternatives(past), part: alternatives(part),
      answer: `${shown(past)} – ${shown(part)}`, full: `${base} – ${alternatives(past).join('/')} – ${alternatives(part).join('/')}`,
      answerLang: 'en', say: `${base}, ${shown(past)}, ${shown(part)}`,
    }));
  }

  /* El or la: every singular Spanish noun with el or la in front of it,
     save the few feminine nouns that take el (el agua, el aula). */
  const EL_FEMININE = ['agua', 'aula'];
  function genusCards() {
    const seen = new Set(), out = [];
    for (const g of GROUPS) for (const t of g.topics) for (const word of t.words || []) {
      if (!word.es) continue;
      const first = shown(word.es);
      const m = /^(el|la) (.+)$/.exec(first);
      if (!m || EL_FEMININE.includes(m[2]) || seen.has(m[2])) continue;
      seen.add(m[2]);
      out.push({
        topic: 'genus', kind: 'genus', dir: 'genus', lang: 'es', key: `es|genus|${stripAccents(m[2])}`,
        front: { text: m[2], lang: 'es' }, sub: shown(word.sv), ask: 'el eller la?', pic: word.pic || null,
        accept: [m[1]], answer: m[1], answerLang: 'es', say: first, options: ['el', 'la'],
      });
    }
    return out;
  }

  function konjCards(topic) {
    return topic.verbs.flatMap(verb => CONJ[verb].forms.map((form, i) => ({
      topic: topic.id, kind: 'konj', dir: 'konj', lang: 'es', key: `es|konj|${verb}|${i}`,
      front: { text: verb, lang: 'es' }, sub: CONJ[verb].sv, person: PERSONS[i], ask: `${PERSONS[i]} …`,
      accept: [form], answer: form, answerLang: 'es', say: `${PERSONS[i].split(' / ')[0]} ${form}`,
      others: CONJ[verb].forms.filter(f => f !== form),
    })));
  }

  /** Which themes a language has, as they are drawn: grammar only where it belongs. */
  function topicsFor(lang) {
    return GROUPS.map(g => ({
      ...g,
      desc: typeof g.desc === 'string' ? g.desc : g.desc[lang],
      topics: g.topics.filter(t => (t.lang ? t.lang === lang : (t.words || []).some(word => word[lang]))),
    })).filter(g => g.topics.length);
  }

  /**
   * The cards of a theme or a list, asked one way or the other.
   *
   * @param {Object} topic - a theme from GROUPS, or a list {id, words: [{sv, x}], lang}
   * @param {'en'|'es'} lang
   * @param {'till'|'fran'} dir - words only; the grammar themes ask their own way
   */
  function cardsFor(topic, lang, dir) {
    if (topic.kind === 'forms') return formsCards(topic);
    if (topic.kind === 'genus') return genusCards();
    if (topic.kind === 'konj') return konjCards(topic);
    const words = topic.list
      ? topic.words.map(([sv, x]) => ({ sv, [lang]: x, pic: null }))
      : (topic.words || []).filter(word => word[lang]);
    return words.map(word => wordCard(word, lang, dir, topic.id));
  }

  /* ── Hints ───────────────────────────────────────────────────────────── */

  /**
   * The first letter of each word and a line for every other letter:
   * "d _ _", "i _ _   c _ _ _ _". A Spanish article is given as it is.
   */
  function letters(answer, lang) {
    const words = String(answer).split(' ');
    const given = lang === 'es' && words.length > 1 && ARTICLES.es.includes(words[0].toLowerCase()) ? 1 : 0;
    return words.map((part, i) => (i < given ? part
      : [...part].map((ch, j) => (j === 0 || !/\p{L}/u.test(ch) ? ch : '_')).join(' '))).join('   ');
  }

  function hint(card) {
    if (card.kind === 'genus') return 'Ord som slutar på -o är oftast el, ord som slutar på -a oftast la – men inte alltid.';
    if (card.kind === 'forms') return `${card.base} – ${letters(card.past[0], 'en')} – ${letters(card.part[0], 'en')}`;
    return letters(card.answer, card.answerLang);
  }

  /* ── Choosing among four ─────────────────────────────────────────────── */

  /**
   * Four answers to choose from: the right one and three others from the
   * same pile, none of them also right for this card.
   *
   * @param {Object} card
   * @param {Object[]} pool - cards of the same kind to take the others from
   * @param {function(): number} random
   */
  function options(card, pool, random) {
    if (card.options) return card.options.slice();
    const right = card.answer;
    /* Nothing that is right too: "leka" and "spela" are both "play". */
    const taken = new Set([normalize(right), ...(card.accept || []).map(normalize)]);
    const candidates = card.kind === 'konj'
      ? card.others.slice()
      : pool.filter(c => c.kind === card.kind && c.answerLang === card.answerLang && c.key !== card.key).map(c => c.answer);
    const picked = [];
    const shuffled = candidates.map(c => [random(), c]).sort((x, y) => x[0] - y[0]).map(x => x[1]);
    for (const c of shuffled) {
      const n = normalize(c);
      if (taken.has(n)) continue;
      taken.add(n);
      picked.push(c);
      if (picked.length === 3) break;
    }
    const all = [right, ...picked];
    return all.map(o => [random(), o]).sort((x, y) => x[0] - y[0]).map(x => x[1]);
  }

  /* ── The pupil's own lists ───────────────────────────────────────────── */

  const LIMITS = Object.freeze({ words: 200, field: 80, name: 40, lists: 50 });

  /**
   * A word list as a teacher writes it, one pair a line, Swedish first:
   *   hund = dog     hund - dog     hund – dog     hund<TAB>dog     hund; dog     hund: dog
   * Lines starting with # are comments; "/" separates answers that are all right.
   *
   * @returns {{words: string[][], errors: {line: number, text: string}[]}}
   */
  function parseList(text) {
    const words = [], errors = [];
    const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n');
    lines.forEach((raw, i) => {
      const line = raw.trim();
      if (!line || line.startsWith('#')) return;
      const m = /^(.+?)\s*(?:\t|=|;|:|\s[-–—]\s)\s*(.+)$/.exec(line);
      if (!m || !m[1].trim() || !m[2].trim()) { errors.push({ line: i + 1, text: line.slice(0, 60) }); return; }
      if (words.length >= LIMITS.words) { errors.push({ line: i + 1, text: `fler än ${LIMITS.words} ord` }); return; }
      const clean = s => s.trim().replace(/\s*\/\s*/g, '|').slice(0, LIMITS.field);
      words.push([clean(m[1]), clean(m[2])]);
    });
    return { words, errors };
  }

  /** The list back as text, for editing. */
  function listText(words) {
    return words.map(([sv, x]) => `${sv.replace(/\|/g, ' / ')} = ${x.replace(/\|/g, ' / ')}`).join('\n');
  }

  /* A list travels in the address after #glosor=, as base64url of its JSON. */
  function encodeShare(list) {
    const json = JSON.stringify({ n: list.name, l: list.lang, w: list.words });
    const bytes = new TextEncoder().encode(json);
    let bin = '';
    for (const b of bytes) bin += String.fromCharCode(b);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  /**
   * A shared list from a link, or null. The link came from anybody, so every
   * field is checked and capped; nothing in it is ever more than text.
   */
  function decodeShare(str) {
    try {
      if (typeof str !== 'string' || str.length > 60000 || !/^[A-Za-z0-9_-]+$/.test(str)) return null;
      const b64 = str.replace(/-/g, '+').replace(/_/g, '/');
      const bin = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
      const json = new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(bin, c => c.charCodeAt(0)));
      const data = JSON.parse(json);
      if (!data || typeof data !== 'object' || !LANGS[data.l] || typeof data.n !== 'string' || !Array.isArray(data.w)) return null;
      const words = data.w
        .filter(p => Array.isArray(p) && p.length === 2 && p.every(s => typeof s === 'string' && s.trim()))
        .slice(0, LIMITS.words)
        .map(([sv, x]) => [sv.trim().slice(0, LIMITS.field), x.trim().slice(0, LIMITS.field)]);
      if (!words.length) return null;
      return { name: data.n.trim().slice(0, LIMITS.name) || 'Delad lista', lang: data.l, words };
    } catch (e) {
      return null;
    }
  }

  /* ── When a word is due: Leitner's boxes ─────────────────────────────── */

  /* Box 1: not known, every day. Box 2: nearly, again after two days.
     Box 3: known, again after a week. Right moves a card up a box - straight
     to 3 if it has never been missed - and wrong sends it back to 1. */
  const DUE_DAYS = { 1: 0, 2: 2, 3: 7 };

  function nextStat(stat, right, today) {
    const st = stat ? { ...stat } : { n: 0, w: 0, box: 0, d: '' };
    st.n += 1;
    if (right) st.box = st.w === 0 ? 3 : Math.min(3, (st.box || 1) + 1);
    else { st.box = 1; st.w += 1; }
    st.d = today;
    return st;
  }

  const dayNumber = iso => Math.floor(Date.parse(`${iso}T12:00:00Z`) / 86400000);

  function isDue(stat, today) {
    if (!stat || !stat.box) return false;
    if (stat.box === 1) return true;
    return !stat.d || dayNumber(today) - dayNumber(stat.d) >= DUE_DAYS[stat.box];
  }

  const STATUS = { 0: 'none', 1: 'ova', 2: 'nara', 3: 'kan' };
  const statusOf = stat => STATUS[(stat && stat.box) || 0];

  return {
    LANGS, GROUPS, IRREGULAR, CONJ, PERSONS, LIMITS,
    numberWord, alternatives, shown, normalize, stripAccents, levenshtein,
    check, checkForms, checkGenus, checkKonj, judge, topicsFor, cardsFor, hint, letters, options,
    parseList, listText, encodeShare, decodeShare, nextStat, isDue, statusOf,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = FC_WORDS;
