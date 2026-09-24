<?php

declare(strict_types=1);

namespace OCA\FaceAttendance\Db;

use JsonSerializable;
use OCP\AppFramework\Db\Entity;

/**
 * @method string getUid()
 * @method void setUid(string $uid)
 * @method string|null getPerson()
 * @method void setPerson(?string $person)
 * @method string getCamera()
 * @method void setCamera(string $camera)
 * @method string getRoom()
 * @method void setRoom(string $room)
 * @method float getScore()
 * @method void setScore(float $score)
 * @method int getTs()
 * @method void setTs(int $ts)
 * @method string|null getSnapshot()
 * @method void setSnapshot(?string $snapshot)
 */
class Event extends Entity implements JsonSerializable {
	protected $uid;
	protected $person;
	protected $camera;
	protected $room;
	protected $score;
	protected $ts;
	protected $snapshot;

	public function __construct() {
		$this->addType('score', 'float');
		$this->addType('ts', 'integer');
	}

	public function jsonSerialize(): array {
		return [
			'id' => $this->id,
			'person' => $this->person,
			'camera' => $this->camera,
			'room' => $this->room,
			'score' => $this->score,
			'ts' => $this->ts,
			'hasSnapshot' => $this->snapshot !== null,
		];
	}
}
