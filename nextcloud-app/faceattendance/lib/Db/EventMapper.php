<?php

declare(strict_types=1);

namespace OCA\FaceAttendance\Db;

use OCP\AppFramework\Db\DoesNotExistException;
use OCP\AppFramework\Db\QBMapper;
use OCP\DB\QueryBuilder\IQueryBuilder;
use OCP\IDBConnection;

/** @template-extends QBMapper<Event> */
class EventMapper extends QBMapper {
	public function __construct(IDBConnection $db) {
		parent::__construct($db, 'fa_events', Event::class);
	}

	public function find(int $id): Event {
		$qb = $this->db->getQueryBuilder();
		$qb->select('*')->from($this->getTableName())
			->where($qb->expr()->eq('id', $qb->createNamedParameter($id, IQueryBuilder::PARAM_INT)));
		return $this->findEntity($qb);
	}

	public function findByUid(string $uid): ?Event {
		$qb = $this->db->getQueryBuilder();
		$qb->select('*')->from($this->getTableName())
			->where($qb->expr()->eq('uid', $qb->createNamedParameter($uid)));
		try {
			return $this->findEntity($qb);
		} catch (DoesNotExistException) {
			return null;
		}
	}

	/**
	 * @param string|null $person null = everybody, '' = only unknown faces
	 * @return Event[]
	 */
	public function findRange(int $from, int $to, ?string $person = null, ?string $room = null, int $limit = 1000): array {
		$qb = $this->db->getQueryBuilder();
		$qb->select('*')->from($this->getTableName())
			->where($qb->expr()->gte('ts', $qb->createNamedParameter($from, IQueryBuilder::PARAM_INT)))
			->andWhere($qb->expr()->lt('ts', $qb->createNamedParameter($to, IQueryBuilder::PARAM_INT)))
			->orderBy('ts', 'DESC')
			->setMaxResults($limit);
		if ($person === '') {
			$qb->andWhere($qb->expr()->isNull('person'));
		} elseif ($person !== null) {
			$qb->andWhere($qb->expr()->eq('person', $qb->createNamedParameter($person)));
		}
		if ($room !== null && $room !== '') {
			$qb->andWhere($qb->expr()->eq('room', $qb->createNamedParameter($room)));
		}
		return $this->findEntities($qb);
	}

	/** @return Event[] */
	public function findOlderThan(int $ts, int $limit = 500): array {
		$qb = $this->db->getQueryBuilder();
		$qb->select('*')->from($this->getTableName())
			->where($qb->expr()->lt('ts', $qb->createNamedParameter($ts, IQueryBuilder::PARAM_INT)))
			->setMaxResults($limit);
		return $this->findEntities($qb);
	}

	public function findNear(string $person, string $room, int $ts, int $window): ?Event {
		$qb = $this->db->getQueryBuilder();
		$qb->select('*')->from($this->getTableName())
			->where($qb->expr()->eq('person', $qb->createNamedParameter($person)))
			->andWhere($qb->expr()->eq('room', $qb->createNamedParameter($room)))
			->andWhere($qb->expr()->gt('ts', $qb->createNamedParameter($ts - $window, IQueryBuilder::PARAM_INT)))
			->andWhere($qb->expr()->lt('ts', $qb->createNamedParameter($ts + $window, IQueryBuilder::PARAM_INT)))
			->orderBy('ts', 'ASC')
			->setMaxResults(1);
		$events = $this->findEntities($qb);
		return $events[0] ?? null;
	}
}
